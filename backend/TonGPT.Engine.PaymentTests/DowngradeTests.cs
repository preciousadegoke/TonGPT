using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using TonGPT.Engine.Models;
using TonGPT.Engine.Services;
using static TonGPT.Engine.Controllers.PaymentController;

sealed partial class UpgradeTests
{
    static void Scheduled(Reply r, bool replay = false)
    {
        Check(r.Code == 200 && r.Body.GetProperty("status").GetString() == "Scheduled", "Prepaid payment must report scheduled, not activated");
        Check(r.Body.GetProperty("paymentId").GetGuid() != Guid.Empty && r.Body.GetProperty("alreadyProcessed").GetBoolean() == replay, "Missing durable scheduling/replay proof");
    }
    async Task<User> Saved(string id)
    {
        await using var db = Db();
        return await db.Users.AsNoTracking().SingleAsync(u => u.TelegramId == id);
    }
    async Task<UpgradeQuote> NextQuote(string id, SubscriptionPlan target, string rail)
    {
        await using var db = Db();
        var reference = Guid.NewGuid().ToString("N");
        var result = Reply(await Controller(db, id, reference).Quote(reference, new(target.ToString(), rail)));
        Check(result.Code == 200, "Subsequent quote rejected");
        return await db.UpgradeQuotes.AsNoTracking().SingleAsync(q => q.Reference == reference);
    }
    static CompletePaymentRequest Renewal(string user, string rail, string plan = "Pro") => new() {
        TelegramId = user, Provider = rail, Plan = plan, ExternalId = Guid.NewGuid().ToString("N"),
        DurationDays = 30, AmountTon = plan == "Starter" ? 10 : 30, AmountStars = plan == "Starter" ? 1335 : 4000,
    };
    public Task ResolverBoundaries()
    {
        var start = new DateTime(2035, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var u = new User { TelegramId = "boundary", Plan = SubscriptionPlan.Pro, SubscriptionExpiry = start,
            PendingPlan = SubscriptionPlan.Starter, PendingStartsAt = start, PendingExpiry = start.AddDays(60) };
        var before = JsonSerializer.Serialize(u);
        foreach (var (time, plan, expiry) in new[] {
            (start.AddTicks(-1), SubscriptionPlan.Pro, (DateTime?)start),
            (start, SubscriptionPlan.Starter, (DateTime?)start.AddDays(60)),
            (start.AddDays(60).AddTicks(-1), SubscriptionPlan.Starter, (DateTime?)start.AddDays(60)),
            (start.AddDays(60), SubscriptionPlan.Free, (DateTime?)null),
            (start.AddYears(1), SubscriptionPlan.Free, (DateTime?)null),
        })
        {
            var actual = EffectiveEntitlement.Resolve(u, time);
            Check(actual.Plan == plan && actual.Expiry == expiry, "Wrong boundary tier/expiry");
            Check((actual.PendingPlan != null) == (time < start), "Active/expired pending period still advertised as future");
        }
        var quote = new UpgradeQuote { Reference = "boundary", TelegramId = u.TelegramId, FromPlan = u.Plan,
            TargetPlan = SubscriptionPlan.Elite, SubscriptionExpiry = start, Provider = "ton",
            PendingPlan = u.PendingPlan, PendingStartsAt = u.PendingStartsAt, PendingExpiry = u.PendingExpiry };
        Check(EffectiveEntitlement.Matches(u, quote, start.AddTicks(-1)) && !EffectiveEntitlement.Matches(u, quote, start), "Quote remained valid across a time-only entitlement transition");
        Check(JsonSerializer.Serialize(u) == before, "Read-time resolver mutated stored state");
        Check(EffectiveEntitlement.Resolve(null, start).Plan == SubscriptionPlan.Free, "Missing user not free");
        u.PendingExpiry = null;
        Check(EffectiveEntitlement.Resolve(u, start.AddTicks(-1)).Plan == SubscriptionPlan.Free, "Incomplete schedule failed open");
        u.PendingPlan = null; u.PendingStartsAt = null;
        Check(EffectiveEntitlement.Resolve(u, start).Plan == SubscriptionPlan.Free, "Expired stored paid plan trusted");
        return Task.CompletedTask;
    }
    public async Task DowngradeMigration()
    {
        await using var db = Db();
        var migrator = db.GetService<IMigrator>();
        await migrator.MigrateAsync("20260919201905_AddUpgradeQuotes");
        var reference = Guid.NewGuid().ToString("N");
        var stamp = DateTime.UtcNow;
        await db.Database.ExecuteSqlInterpolatedAsync($"INSERT INTO \"UpgradeQuotes\" (\"Reference\", \"TelegramId\", \"FromPlan\", \"TargetPlan\", \"SubscriptionExpiry\", \"EntitlementVersion\", \"Provider\", \"ExpectedUnits\", \"CreatedAt\", \"ValidUntil\") VALUES ({reference}, 'old-quote', 1, 2, {stamp.AddDays(10)}, 0, 'ton', 10000000000, {stamp}, {stamp.AddMinutes(5)})");
        await migrator.MigrateAsync();
        var old = await db.UpgradeQuotes.AsNoTracking().SingleAsync(q => q.Reference == reference);
        Check(old.Kind == "upgrade" && old.PendingPlan == null && old.ExpectedUnits == 10000000000, "Migration changed existing quote semantics");
        await migrator.MigrateAsync("20260919201905_AddUpgradeQuotes");
        await migrator.MigrateAsync();
        Check((await db.UpgradeQuotes.AsNoTracking().SingleAsync(q => q.Reference == reference)).Kind == "upgrade", "Rollback/reapply lost legacy quote");
        var q = await Quote("ton", SubscriptionPlan.Pro, SubscriptionPlan.Starter);
        try
        {
            await migrator.MigrateAsync("20260919201905_AddUpgradeQuotes");
            throw new Exception("Rollback reinterpreted an outstanding downgrade quote as an upgrade");
        }
        catch (Npgsql.PostgresException ex) when (ex.SqlState == "P0001") { }
        Scheduled(await Complete(Receipt(q)));
        var scheduled = await Saved(q.TelegramId);
        try
        {
            await migrator.MigrateAsync("20260919201905_AddUpgradeQuotes");
            throw new Exception("Rollback discarded paid downgrade coverage");
        }
        catch (Npgsql.PostgresException ex) when (ex.SqlState == "P0001") { }
        var restored = await Saved(q.TelegramId);
        Check(restored.Plan == scheduled.Plan && restored.SubscriptionExpiry == scheduled.SubscriptionExpiry && restored.PendingExpiry == scheduled.PendingExpiry, "Rejected rollback altered paid coverage");
        Check(await db.Payments.AnyAsync(p => p.TelegramUserId == q.TelegramId), "Rollback lost receipt");
        Check(!db.Database.HasPendingModelChanges(), "Pending downgrade snapshot mismatch");
    }
    public async Task PrepaidCycles(string rail)
    {
        var q = await Quote(rail, SubscriptionPlan.Pro, SubscriptionPlan.Starter);
        Check(q.Kind == "downgrade" && q.ExpectedUnits == (rail == "ton" ? 10000000000 : 1335), "Downgrade must charge the lower tier's entire 30-day price");
        var receipt = Receipt(q);
        Scheduled(await Complete(receipt)); Scheduled(await Complete(receipt), true);
        var u = await Saved(q.TelegramId);
        Check(u.Plan == q.FromPlan && u.SubscriptionExpiry == q.SubscriptionExpiry && u.PendingStartsAt == q.SubscriptionExpiry && u.PendingExpiry == q.SubscriptionExpiry.AddDays(30), "Scheduling changed current coverage or wrong prepaid dates");
        var next = await NextQuote(q.TelegramId, SubscriptionPlan.Starter, rail);
        Scheduled(await Complete(Receipt(next)));
        u = await Saved(q.TelegramId);
        Check(u.PendingExpiry == q.SubscriptionExpiry.AddDays(60) && u.EntitlementVersion == 2, "Distinct prepaid cycle not added once");
        await using var db = Db();
        var status = Reply(await Controller(db, q.TelegramId, q.Reference).Status(q.Reference));
        Check(status.Body.GetProperty("status").GetString() == "scheduled", "Checkout incorrectly promises immediate lower-tier activation");
        var other = Reply(await Controller(db, "999999", q.Reference).Status(q.Reference));
        Check(other.Body.GetProperty("status").GetString() == "pending" && !other.Body.TryGetProperty("paymentId", out _), "Cross-user schedule disclosure");
        Check(await db.ActivityLogs.CountAsync(a => a.TelegramId == q.TelegramId && a.Action == "payment_scheduled" && a.Success) == 2, "Wrong scheduling audit count");
    }
    public async Task ShiftAndUpgrade(string rail)
    {
        var q = await Quote(rail, SubscriptionPlan.Pro, SubscriptionPlan.Starter);
        Scheduled(await Complete(Receipt(q)));
        var stale = await NextQuote(q.TelegramId, SubscriptionPlan.Starter, rail);
        var renewal = Renewal(q.TelegramId, rail);
        Activated(await Complete(renewal)); Activated(await Complete(renewal), true);
        var u = await Saved(q.TelegramId);
        Check(u.SubscriptionExpiry == q.SubscriptionExpiry.AddDays(30) && u.PendingStartsAt == u.SubscriptionExpiry && u.PendingExpiry == q.SubscriptionExpiry.AddDays(60), "Renewal lost prepaid time or failed to shift both dates");
        await Held(await Complete(Receipt(stale)), stale, "EntitlementChanged", stale.ExpectedUnits);
        var upgrade = await NextQuote(q.TelegramId, SubscriptionPlan.Elite, rail);
        Activated(await Complete(Receipt(upgrade)));
        var after = await Saved(q.TelegramId);
        Check(after.Plan == SubscriptionPlan.Elite && after.SubscriptionExpiry == u.SubscriptionExpiry && after.PendingPlan == u.PendingPlan && after.PendingStartsAt == u.PendingStartsAt && after.PendingExpiry == u.PendingExpiry, "Upgrade erased/moved prepaid downgrade");
    }
    public async Task ActivePendingPurchases(string rail)
    {
        foreach (var upgrade in new[] { false, true })
        {
            var q = await Quote(rail, SubscriptionPlan.Pro, SubscriptionPlan.Starter);
            Scheduled(await Complete(Receipt(q)));
            var start = DateTimeOffset.FromUnixTimeSeconds(DateTimeOffset.UtcNow.ToUnixTimeSeconds()).UtcDateTime.AddDays(-1);
            var end = start.AddDays(30);
            await using var db = Db();
            await db.Users.Where(u => u.TelegramId == q.TelegramId).ExecuteUpdateAsync(s => s.SetProperty(u => u.SubscriptionExpiry, start).SetProperty(u => u.PendingStartsAt, start).SetProperty(u => u.PendingExpiry, end));
            if (upgrade)
            {
                var next = await NextQuote(q.TelegramId, SubscriptionPlan.Pro, rail);
                Check(next.FromPlan == SubscriptionPlan.Starter && next.SubscriptionExpiry == end, "Quote trusted old stored tier after boundary");
                Activated(await Complete(Receipt(next)));
            }
            else Activated(await Complete(Renewal(q.TelegramId, rail, "Starter")));
            var user = await Saved(q.TelegramId);
            Check(user.Plan == (upgrade ? SubscriptionPlan.Pro : SubscriptionPlan.Starter) && user.SubscriptionExpiry == (upgrade ? end : end.AddDays(30)), "Purchase after transition used old entitlement");
            Check(user.PendingPlan == null && user.PendingStartsAt == null && user.PendingExpiry == null, "Consumed pending period not normalized inside payment");
        }
    }
    public async Task DowngradeMismatch(string rail)
    {
        foreach (var delta in new[] { -1, 1 })
        {
            var q = await Quote(rail, SubscriptionPlan.Pro, SubscriptionPlan.Starter);
            var r = Receipt(q); r.PaidUnits += delta;
            await Held(await Complete(r), q, "AmountMismatch", r.PaidUnits!.Value);
            await Held(await Complete(r), q, "AmountMismatch", r.PaidUnits.Value);
            var user = await Saved(q.TelegramId);
            Check(user.PendingPlan == null && user.Plan == q.FromPlan && user.SubscriptionExpiry == q.SubscriptionExpiry, "Mismatch scheduled or altered coverage");
        }
    }
    public async Task DowngradeConflict(string rail)
    {
        var q = await Quote(rail, SubscriptionPlan.Elite, SubscriptionPlan.Pro);
        var conflicting = await NextQuote(q.TelegramId, SubscriptionPlan.Starter, rail);
        Scheduled(await Complete(Receipt(q)));
        await Held(await Complete(Receipt(conflicting)), conflicting, "EntitlementChanged", conflicting.ExpectedUnits);
        await using var db = Db(); var reference = Guid.NewGuid().ToString("N");
        Check(Reply(await Controller(db, q.TelegramId, reference).Quote(reference, new("Starter", rail))).Code == 409, "Existing paid future tier silently replaced");
        Check((await Saved(q.TelegramId)).PendingPlan == SubscriptionPlan.Pro, "Conflicting receipt replaced pending tier");
    }
    public async Task DowngradeRollback(string rail)
    {
        var q = await Quote(rail, SubscriptionPlan.Pro, SubscriptionPlan.Starter);
        var r = Receipt(q); var failure = new FailAfterUpgradeSave();
        Check((await Complete(r, failure)).Code == 503 && failure.Triggered, "Schedule rollback was not injected after SQL");
        var u = await Saved(q.TelegramId);
        Check(u.PendingPlan == null && u.EntitlementVersion == 0 && u.SubscriptionExpiry == q.SubscriptionExpiry, "Schedule rollback left entitlement changes");
        await using var db = Db();
        Check(!await db.Payments.AnyAsync(p => p.TelegramUserId == q.TelegramId) && !await db.ActivityLogs.AnyAsync(a => a.TelegramId == q.TelegramId), "Schedule rollback left payment/audit");
        Check((await db.UpgradeQuotes.SingleAsync(x => x.Reference == q.Reference)).AppliedPaymentId == null, "Schedule rollback consumed quote");
        Scheduled(await Complete(r)); Scheduled(await Complete(r), true);
        var renewalFailure = new FailAfterRenewalUpdate();
        Check((await Complete(Renewal(q.TelegramId, rail), renewalFailure)).Code == 503 && renewalFailure.Triggered, "Renewal shift rollback did not run");
        u = await Saved(q.TelegramId);
        Check(u.PendingStartsAt == q.SubscriptionExpiry && u.PendingExpiry == q.SubscriptionExpiry.AddDays(30) && u.SubscriptionExpiry == q.SubscriptionExpiry, "Rolled-back renewal shifted pending dates");
    }
    public async Task DowngradeConcurrency(string rail, string mode)
    {
        var q = await Quote(rail, SubscriptionPlan.Pro, SubscriptionPlan.Starter);
        var first = Receipt(q);
        var second = mode switch {
            "duplicate" => first,
            "same-quote" => Receipt(q),
            "renewal" => Renewal(q.TelegramId, rail == "ton" ? "telegram_stars" : "ton"),
            "upgrade" => Receipt(await NextQuote(q.TelegramId, SubscriptionPlan.Elite, rail)),
            _ => Receipt(await NextQuote(q.TelegramId, SubscriptionPlan.Starter, rail == "ton" ? "telegram_stars" : "ton")),
        };
        var barrier = new UpgradeLockBarrier();
        var replies = await Task.WhenAll(Complete(first, barrier), Complete(second, barrier));
        Check(replies.All(r => r.Code == 200), "Concurrent schedule lost receipt");
        var user = await Saved(q.TelegramId);
        await using var db = Db();
        Check(await db.Payments.CountAsync(p => p.TelegramUserId == q.TelegramId) == (mode == "duplicate" ? 1 : 2), "Wrong concurrent payment count");
        if (mode == "duplicate")
            Check(replies.Count(r => r.Body.GetProperty("alreadyProcessed").GetBoolean()) == 1 && user.PendingExpiry == q.SubscriptionExpiry.AddDays(30), "Duplicate schedule added time twice");
        else if (mode == "renewal")
        {
            Check(user.SubscriptionExpiry == q.SubscriptionExpiry.AddDays(30), "Concurrent renewal lost purchased days");
            Check(user.PendingPlan == null || (user.PendingStartsAt == user.SubscriptionExpiry && user.PendingExpiry == user.SubscriptionExpiry!.Value.AddDays(30)), "Concurrent schedule failed to follow renewal");
        }
        else
        {
            Check(replies.Count(r => r.Body.GetProperty("status").GetString() == "ReconciliationRequired") == 1, "Stale concurrent quote not held");
            Check(user.EntitlementVersion == 1, "Concurrent quotes both changed entitlement");
        }
    }

    public async Task ExpiredCoverage(string rail)
    {
        var q = await Quote(rail, SubscriptionPlan.Pro, SubscriptionPlan.Starter);
        Scheduled(await Complete(Receipt(q)));
        var end = DateTime.UtcNow.AddDays(-1);
        await using var db = Db();
        await db.Users.Where(u => u.TelegramId == q.TelegramId).ExecuteUpdateAsync(s => s
            .SetProperty(u => u.SubscriptionExpiry, end.AddDays(-30))
            .SetProperty(u => u.PendingStartsAt, end.AddDays(-30)).SetProperty(u => u.PendingExpiry, end));
        var stored = await Saved(q.TelegramId);
        Check(EffectiveEntitlement.Resolve(stored, DateTime.UtcNow).Plan == SubscriptionPlan.Free, "Expired prepaid coverage is still premium");
        var reference = Guid.NewGuid().ToString("N");
        Check(Reply(await Controller(db, q.TelegramId, reference).Quote(reference, new("Starter", rail))).Body.GetProperty("kind").GetString() == "cycle", "Expired schedule charged a tier-change price");
        var started = DateTime.UtcNow;
        Activated(await Complete(Renewal(q.TelegramId, rail, "Starter")));
        var user = await Saved(q.TelegramId);
        Check(user.Plan == SubscriptionPlan.Starter && user.PendingPlan == null && user.SubscriptionExpiry >= started.AddDays(30) && user.SubscriptionExpiry <= DateTime.UtcNow.AddDays(30), "New cycle resurrected expired coverage or lost time");
    }
    public async Task DowngradeAfterTransition(string rail)
    {
        var q = await Quote(rail, SubscriptionPlan.Elite, SubscriptionPlan.Pro);
        Scheduled(await Complete(Receipt(q)));
        var start = DateTimeOffset.FromUnixTimeSeconds(DateTimeOffset.UtcNow.ToUnixTimeSeconds()).UtcDateTime.AddDays(-1);
        await using var db = Db();
        await db.Users.Where(u => u.TelegramId == q.TelegramId).ExecuteUpdateAsync(s => s.SetProperty(u => u.SubscriptionExpiry, start).SetProperty(u => u.PendingStartsAt, start).SetProperty(u => u.PendingExpiry, start.AddDays(30)));
        var next = await NextQuote(q.TelegramId, SubscriptionPlan.Starter, rail);
        Check(next.FromPlan == SubscriptionPlan.Pro, "Second downgrade quoted against expired Elite");
        var request = Receipt(next);
        var failure = new FailAfterUpgradeSave();
        Check((await Complete(request, failure)).Code == 503 && failure.Triggered, "Transition normalization rollback not exercised");
        var original = await Saved(q.TelegramId);
        Check(original.Plan == SubscriptionPlan.Elite && original.PendingPlan == SubscriptionPlan.Pro && original.PendingStartsAt == start, "Rollback normalized the old pending period");
        Scheduled(await Complete(request));
        var user = await Saved(q.TelegramId);
        Check(user.Plan == SubscriptionPlan.Pro && user.SubscriptionExpiry == start.AddDays(30) && user.PendingPlan == SubscriptionPlan.Starter && user.PendingStartsAt == start.AddDays(30) && user.PendingExpiry == start.AddDays(60), "New schedule did not follow effective coverage");
    }

    IEnumerable<(string Name, Func<Task> Run)> DowngradeCases()
    {
        yield return ("resolver: exact boundaries and read purity", ResolverBoundaries);
        yield return ("pending downgrade migration/rollback on disposable PostgreSQL", DowngradeMigration);
        foreach (var rail in new[] { "ton", "telegram_stars" })
        {
            yield return ($"{rail}: prepaid downgrade cycles, replay and scoped status", () => PrepaidCycles(rail));
            yield return ($"{rail}: renewal shifts and upgrade preserves downgrade", () => ShiftAndUpgrade(rail));
            yield return ($"{rail}: purchases after pending tier becomes active", () => ActivePendingPurchases(rail));
            yield return ($"{rail}: expired prepaid coverage and new cycle", () => ExpiredCoverage(rail));
            yield return ($"{rail}: downgrade after transition and normalization rollback", () => DowngradeAfterTransition(rail));
            yield return ($"{rail}: downgrade over/underpayment held", () => DowngradeMismatch(rail));
            yield return ($"{rail}: conflicting prepaid tier held/rejected", () => DowngradeConflict(rail));
            yield return ($"{rail}: scheduling and renewal-shift rollback", () => DowngradeRollback(rail));
            foreach (var mode in new[] { "duplicate", "same-quote", "cross-rail", "renewal", "upgrade" })
                yield return ($"{rail}: concurrent downgrade/{mode}", () => DowngradeConcurrency(rail, mode));
        }
    }
}
