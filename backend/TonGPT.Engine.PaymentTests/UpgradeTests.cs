using System.Security.Cryptography;
using System.Data.Common;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using TonGPT.Engine.Controllers;
using TonGPT.Engine.Data;
using TonGPT.Engine.Models;
using TonGPT.Engine.Services;
using static TonGPT.Engine.Controllers.PaymentController;

sealed class UpgradeTests(Func<IInterceptor[], AppDbContext> context)
{
    const string Secret = "isolated-upgrade-test-secret";
    static long nextUser = 800000;
    static void Check(bool value, string message) { if (!value) throw new Exception(message); }
    static Reply Reply(IActionResult result) => result switch {
        ObjectResult r => new(r.StatusCode ?? 200, JsonSerializer.SerializeToElement(r.Value)),
        StatusCodeResult r => new(r.StatusCode, default),
        _ => throw new Exception("Unexpected result"),
    };
    AppDbContext Db(params IInterceptor[] interceptors) => context(interceptors);
    static CheckoutController Controller(AppDbContext db, string user, string reference, bool signed = true)
    {
        var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["WalletLinkSigningSecret"] = Secret }).Build();
        var controller = new CheckoutController(db, config) { ControllerContext = new() { HttpContext = new DefaultHttpContext() } };
        var body = $"co1|{user}|{reference}|{DateTimeOffset.UtcNow.ToUnixTimeSeconds() + 60}|upgrade-test";
        if (signed) controller.Request.Headers["X-Checkout-Assertion"] = body + "|" + Convert.ToHexString(HMACSHA256.HashData(Encoding.UTF8.GetBytes(Secret), Encoding.UTF8.GetBytes(body))).ToLowerInvariant();
        return controller;
    }
    async Task<Reply> Complete(CompletePaymentRequest request, params IInterceptor[] interceptors)
    {
        await using var db = Db(interceptors);
        return Reply(await new PaymentController(db, NullLogger<PaymentController>.Instance).Complete(request));
    }
    async Task<UpgradeQuote> Quote(string provider, SubscriptionPlan from = SubscriptionPlan.Starter, SubscriptionPlan to = SubscriptionPlan.Pro, TimeSpan? remaining = null)
    {
        var user = Interlocked.Increment(ref nextUser).ToString();
        var now = DateTimeOffset.FromUnixTimeSeconds(DateTimeOffset.UtcNow.ToUnixTimeSeconds()).UtcDateTime;
        var reference = Guid.NewGuid().ToString("N");
        await using var db = Db();
        db.Users.Add(new User { TelegramId = user, Plan = from, SubscriptionExpiry = now + (remaining ?? TimeSpan.FromDays(15)) });
        await db.SaveChangesAsync();
        var response = Reply(await Controller(db, user, reference).Quote(reference, new(to.ToString(), provider)));
        Check(response.Code == 200 && response.Body.GetProperty("kind").GetString() == "upgrade", "Quote endpoint did not issue an upgrade");
        return await db.UpgradeQuotes.AsNoTracking().SingleAsync(q => q.Reference == reference);
    }
    static CompletePaymentRequest Receipt(UpgradeQuote q) => new() {
        TelegramId = q.TelegramId, Plan = q.TargetPlan.ToString(), Provider = q.Provider,
        ExternalId = Guid.NewGuid().ToString("N"), QuoteReference = q.Reference,
        PaidUnits = q.ExpectedUnits, PaidAt = q.CreatedAt, DurationDays = 0,
    };
    static void Activated(Reply r, bool replay = false)
    {
        Check(r.Code == 200 && r.Body.GetProperty("status").GetString() == (replay ? "AlreadyProcessed" : "Activated"), "Expected committed activation");
        Check(r.Body.GetProperty("alreadyProcessed").GetBoolean() == replay, "Wrong replay flag");
    }
    async Task Held(Reply r, UpgradeQuote q, string reason, long actual)
    {
        Check(r.Code == 200 && r.Body.GetProperty("held").GetBoolean(), "Receipt must be durably held, not dropped or activated");
        var id = r.Body.GetProperty("paymentId").GetGuid();
        await using var db = Db();
        var payment = await db.Payments.SingleAsync(p => p.Id == id);
        var hold = await db.PaymentReconciliations.SingleAsync(p => p.PaymentId == id);
        Check(payment.Status == "ReconciliationRequired" && hold.Reason == reason && hold.ActualUnits == actual, "Reconciliation ledger lost reason/amount");
        Check(hold.Currency == (payment.Provider == "ton" ? "TON" : "XTR"), "Wrong receipt currency");
        Check(await db.ActivityLogs.AnyAsync(a => a.TelegramId == payment.TelegramUserId && a.Action == "payment_held" && !a.Success), "Held receipt missing failure audit");
    }
    public async Task Migration()
    {
        await using var db = Db();
        var migrator = db.GetService<IMigrator>();
        await migrator.MigrateAsync("20260914000100_AddCheckoutReference");
        var user = "legacy-upgrade-migration";
        var expiry = new DateTime(2035, 1, 2, 3, 4, 5, DateTimeKind.Utc);
        await db.Database.ExecuteSqlInterpolatedAsync($"INSERT INTO \"Users\" (\"TelegramId\", \"Plan\", \"SubscriptionExpiry\", \"CreatedAt\") VALUES ({user}, 2, {expiry}, {DateTime.UtcNow})");
        await migrator.MigrateAsync();
        var before = await db.Users.AsNoTracking().SingleAsync(u => u.TelegramId == user);
        Check(before.Plan == SubscriptionPlan.Pro && before.SubscriptionExpiry == expiry && before.EntitlementVersion == 0, "Upgrade migration changed legacy entitlement");
        var quote = await Quote("ton");
        var receipt = Receipt(quote); receipt.PaidUnits++;
        await Held(await Complete(receipt), quote, "AmountMismatch", quote.ExpectedUnits + 1);
        await migrator.MigrateAsync("20260914000100_AddCheckoutReference");
        await migrator.MigrateAsync();
        var after = await db.Users.AsNoTracking().SingleAsync(u => u.TelegramId == user);
        Check(after.Plan == before.Plan && after.SubscriptionExpiry == expiry, "Rollback/reapply changed legacy entitlement");
        Check(!db.Database.HasPendingModelChanges(), "Upgrade snapshot does not match model");
    }
    public Task Pricing()
    {
        foreach (var rail in new[] { "ton", "telegram_stars" })
        foreach (var from in new[] { SubscriptionPlan.Starter, SubscriptionPlan.Pro, SubscriptionPlan.ProPlus })
        foreach (var to in new[] { SubscriptionPlan.Pro, SubscriptionPlan.ProPlus, SubscriptionPlan.Elite }.Where(t => t > from))
        foreach (var duration in new[] { TimeSpan.FromTicks(1), TimeSpan.FromDays(1.25), TimeSpan.FromDays(15), TimeSpan.FromDays(30), TimeSpan.FromDays(60) })
        {
            var prices = rail == "ton" ? new long[] { 0, 10_000_000_000, 30_000_000_000, 60_000_000_000, 120_000_000_000 } : new long[] { 0, 1335, 4000, 8000, 16000 };
            var expected = (long)decimal.Ceiling((decimal)duration.Ticks * (prices[(int)to] - prices[(int)from]) / TimeSpan.FromDays(30).Ticks);
            Check(UpgradePricing.Units(from, to, rail, duration) == expected, $"Proration/ceiling incorrect for {rail} {from}->{to} {duration}");
        }
        foreach (var remaining in new[] { TimeSpan.Zero, TimeSpan.FromTicks(-1) })
        {
            try { UpgradePricing.Units(SubscriptionPlan.Starter, SubscriptionPlan.Pro, "ton", remaining); throw new Exception("Expired upgrade accepted"); }
            catch (ArgumentException) { }
        }
        return Task.CompletedTask;
    }
    public async Task RenewalPeriods(string rail)
    {
        var q = await Quote(rail);
        foreach (var days in new[] { int.MinValue, -1, 0, 1, 17, 29, 31, 60, int.MaxValue })
        {
            var r = new CompletePaymentRequest { TelegramId = q.TelegramId, Plan = "Starter", Provider = rail, ExternalId = Guid.NewGuid().ToString("N"), DurationDays = days, AmountTon = 10, AmountStars = 1335 };
            Check((await Complete(r)).Code == 400, $"Unsupported period {days} accepted");
        }
        await using var db = Db();
        Check(!await db.Payments.AnyAsync(p => p.TelegramUserId == q.TelegramId), "Rejected renewal wrote a payment");
        var request = new CompletePaymentRequest { TelegramId = q.TelegramId, Plan = "Starter", Provider = rail, ExternalId = Guid.NewGuid().ToString("N"), DurationDays = 30, AmountTon = 10, AmountStars = 1335 };
        Activated(await Complete(request));
        Activated(await Complete(request), true);
        request.DurationDays = 17;
        Activated(await Complete(request), true);
        var user = await db.Users.AsNoTracking().SingleAsync(u => u.TelegramId == q.TelegramId);
        Check(user.Plan == q.FromPlan && user.SubscriptionExpiry == q.SubscriptionExpiry.AddDays(30) && user.EntitlementVersion == 1, "Same-tier renewal changed plan or failed atomic extension");
    }
    public async Task Activation(string rail)
    {
        var q = await Quote(rail, SubscriptionPlan.Pro, SubscriptionPlan.Elite, TimeSpan.FromDays(1.25));
        var expected = (long)decimal.Ceiling((decimal)(q.SubscriptionExpiry - q.CreatedAt).Ticks * (rail == "ton" ? 90_000_000_000L : 12000L) / TimeSpan.FromDays(30).Ticks);
        Check(q.ExpectedUnits == expected, "Persisted quote differs from actual remaining-time price");
        var request = Receipt(q);
        Activated(await Complete(request));
        Activated(await Complete(request), true);
        await using var db = Db();
        var user = await db.Users.SingleAsync(u => u.TelegramId == q.TelegramId);
        Check(user.Plan == q.TargetPlan && user.SubscriptionExpiry == q.SubscriptionExpiry && user.EntitlementVersion == 1, "Upgrade must switch plan once without extending expiry");
        Check(await db.Payments.CountAsync(p => p.TelegramUserId == q.TelegramId) == 1, "Replay duplicated receipt");
        Check((await db.UpgradeQuotes.SingleAsync(x => x.Reference == q.Reference)).AppliedPaymentId != null, "Quote not consumed");
        var status = Reply(await Controller(db, q.TelegramId, q.Reference).Status(q.Reference));
        Check(status.Body.GetProperty("status").GetString() == "activated", "Checkout did not confirm upgrade");
    }
    public async Task Mismatch(string rail, int delta)
    {
        var q = await Quote(rail);
        var request = Receipt(q); request.PaidUnits += delta;
        var first = await Complete(request);
        await Held(first, q, "AmountMismatch", request.PaidUnits!.Value);
        var replay = await Complete(request);
        Check(replay.Body.GetProperty("alreadyProcessed").GetBoolean() && first.Body.GetProperty("paymentId").GetGuid() == replay.Body.GetProperty("paymentId").GetGuid(), "Held replay duplicated receipt");
        request.PaidUnits = q.ExpectedUnits;
        await Held(await Complete(request), q, "AmountMismatch", q.ExpectedUnits + delta);
        await using var db = Db();
        var user = await db.Users.SingleAsync(u => u.TelegramId == q.TelegramId);
        Check(user.Plan == q.FromPlan && user.SubscriptionExpiry == q.SubscriptionExpiry && user.EntitlementVersion == 0, "Mismatched quote changed entitlement");
        Check((await db.UpgradeQuotes.SingleAsync(x => x.Reference == q.Reference)).AppliedPaymentId == null, "Held receipt consumed quote");
        Check(await db.Payments.CountAsync(p => p.TelegramUserId == q.TelegramId) == 1, "Held replay wrote another receipt");
        var status = Reply(await Controller(db, q.TelegramId, q.Reference).Status(q.Reference));
        Check(status.Body.GetProperty("status").GetString() == "reconciliation_required", "Held status was reported as activation/pending");
        var other = Reply(await Controller(db, "999999", q.Reference).Status(q.Reference));
        Check(other.Body.GetProperty("status").GetString() == "pending" && !other.Body.TryGetProperty("paymentId", out _), "Held status leaked across users");
    }
    public async Task StateConflict(string rail)
    {
        var q = await Quote(rail);
        var renewal = new CompletePaymentRequest { TelegramId = q.TelegramId, Plan = "Starter", Provider = rail, ExternalId = Guid.NewGuid().ToString("N"), AmountTon = 10, AmountStars = 1335 };
        Activated(await Complete(renewal));
        await Held(await Complete(Receipt(q)), q, "EntitlementChanged", q.ExpectedUnits);
        await using var db = Db();
        var u = await db.Users.SingleAsync(u => u.TelegramId == q.TelegramId);
        Check(u.Plan == q.FromPlan && u.SubscriptionExpiry == q.SubscriptionExpiry.AddDays(30), "Stale quote overwrote renewed entitlement");
        Check(Reply(await Controller(db, q.TelegramId, q.Reference).ValidateQuote(q.Reference)).Code == 409, "Prepayment validation accepted stale quote");
    }
    public async Task PaymentWindow(string rail)
    {
        foreach (var mode in new[] { "early", "late", "missing", "delayed" })
        {
            var q = await Quote(rail);
            var r = Receipt(q);
            if (mode == "early") r.PaidAt = q.CreatedAt.AddSeconds(-1);
            if (mode == "late") r.PaidAt = q.ValidUntil.AddSeconds(1);
            if (mode == "missing") r.PaidAt = null;
            if (mode == "delayed")
            {
                await using var db = Db();
                await db.UpgradeQuotes.Where(x => x.Reference == q.Reference).ExecuteUpdateAsync(s => s.SetProperty(x => x.CreatedAt, q.CreatedAt.AddMinutes(-10)).SetProperty(x => x.ValidUntil, q.CreatedAt.AddMinutes(-5)));
                r.PaidAt = q.CreatedAt.AddMinutes(-7);
                Check(Reply(await Controller(db, q.TelegramId, q.Reference).ValidateQuote(q.Reference)).Code == 409, "Expired quote allowed a new payment");
                Activated(await Complete(r)); // Provider paid on time, delivery was late.
            }
            else await Held(await Complete(r), q, mode == "missing" ? "MissingPaymentTimestamp" : "PaymentOutsideQuoteWindow", q.ExpectedUnits);
        }
    }
    public async Task Authorization(string rail)
    {
        var q = await Quote(rail);
        await using var db = Db();
        Check(Reply(await Controller(db, q.TelegramId, q.Reference, false).ValidateQuote(q.Reference)).Code == 403, "API key alone can read quote");
        Check(Reply(await Controller(db, "999999", q.Reference).ValidateQuote(q.Reference)).Code == 404, "Other user can read quote");
        Check(Reply(await Controller(db, q.TelegramId, q.Reference, false).Quote(q.Reference, new("Pro", rail))).Code == 403, "API key alone can create quote");
        var r = Receipt(q); r.TelegramId = "999999";
        await Held(await Complete(r), q, "QuoteUnavailable", q.ExpectedUnits);
        r.TelegramId = q.TelegramId;
        Check((await Complete(r)).Code == 409, "Cross-user duplicate exposed held payment");
        var own = Receipt(q); Activated(await Complete(own)); own.TelegramId = "999999";
        Check((await Complete(own)).Code == 409, "Cross-user duplicate exposed completed payment");
    }
    public async Task Rollback(string rail, bool mismatch)
    {
        var q = await Quote(rail);
        var request = Receipt(q); if (mismatch) request.PaidUnits++;
        var failure = new FailAfterUpgradeSave();
        Check((await Complete(request, failure)).Code == 503 && failure.Triggered, "Failure must follow actual SQL writes and return retryable");
        await using var db = Db();
        Check(!await db.Payments.AnyAsync(p => p.TelegramUserId == q.TelegramId), "Rolled-back receipt survived");
        Check(!await db.PaymentReconciliations.AnyAsync(p => p.QuoteReference == q.Reference), "Rolled-back hold survived");
        Check(!await db.ActivityLogs.AnyAsync(a => a.TelegramId == q.TelegramId), "Rolled-back audit survived");
        var user = await db.Users.SingleAsync(u => u.TelegramId == q.TelegramId);
        Check(user.Plan == q.FromPlan && user.SubscriptionExpiry == q.SubscriptionExpiry && user.EntitlementVersion == 0, "Rolled-back entitlement survived");
        Check((await db.UpgradeQuotes.SingleAsync(x => x.Reference == q.Reference)).AppliedPaymentId == null, "Rollback consumed quote");
        var retry = await Complete(request);
        if (mismatch) await Held(retry, q, "AmountMismatch", request.PaidUnits!.Value); else Activated(retry);
    }
    public async Task Concurrent(string rail, bool sameReceipt)
    {
        var q = await Quote(rail);
        var first = Receipt(q); var second = sameReceipt ? first : Receipt(q);
        var barrier = new UpgradeLockBarrier();
        var results = await Task.WhenAll(Complete(first, barrier), Complete(second, barrier));
        Check(results.All(r => r.Code == 200), "Concurrent receipt was lost");
        Check(results.Count(r => r.Body.GetProperty("status").GetString() == "Activated") == 1, "Concurrent quote applied more than once");
        if (sameReceipt) Check(results.Count(r => r.Body.GetProperty("alreadyProcessed").GetBoolean()) == 1, "Same receipt not deduplicated");
        else await Held(results.Single(r => r.Body.GetProperty("status").GetString() == "ReconciliationRequired"), q, "QuoteAlreadyApplied", q.ExpectedUnits);
        await using var db = Db();
        var u = await db.Users.SingleAsync(u => u.TelegramId == q.TelegramId);
        Check(u.EntitlementVersion == 1 && u.SubscriptionExpiry == q.SubscriptionExpiry, "Concurrent quote extended time or applied twice");
        Check(await db.Payments.CountAsync(p => p.TelegramUserId == q.TelegramId) == (sameReceipt ? 1 : 2), "Wrong concurrent ledger count");
    }
    public async Task SeparateQuotes(string rail, bool crossRail = false)
    {
        var q = await Quote(rail);
        var reference = Guid.NewGuid().ToString("N");
        UpgradeQuote second;
        await using (var db = Db())
        {
            var otherRail = crossRail ? (rail == "ton" ? "telegram_stars" : "ton") : rail;
            Check(Reply(await Controller(db, q.TelegramId, reference).Quote(reference, new("Pro", otherRail))).Code == 200, "Second quote unavailable");
            second = await db.UpgradeQuotes.AsNoTracking().SingleAsync(x => x.Reference == reference);
        }
        var barrier = new UpgradeLockBarrier();
        var results = await Task.WhenAll(Complete(Receipt(q), barrier), Complete(Receipt(second), barrier));
        Check(results.Count(r => r.Code == 200 && r.Body.GetProperty("status").GetString() == "Activated") == 1, "Different concurrent quotes both activated");
        var heldIndex = Array.FindIndex(results, r => r.Body.GetProperty("status").GetString() == "ReconciliationRequired");
        var heldQuote = heldIndex == 0 ? q : second;
        await Held(results[heldIndex], heldQuote, "EntitlementChanged", heldQuote.ExpectedUnits);
        await using var check = Db();
        Check((await check.Users.SingleAsync(u => u.TelegramId == q.TelegramId)).EntitlementVersion == 1, "Concurrent quotes applied twice");
    }
    public async Task RenewalRace(string rail)
    {
        var q = await Quote(rail);
        var renewal = new CompletePaymentRequest { TelegramId = q.TelegramId, Plan = "Starter", Provider = rail == "ton" ? "telegram_stars" : "ton", ExternalId = Guid.NewGuid().ToString("N"), AmountTon = 10, AmountStars = 1335 };
        var barrier = new UpgradeLockBarrier();
        var results = await Task.WhenAll(Complete(Receipt(q), barrier), Complete(renewal, barrier));
        Check(results.All(r => r.Code == 200), "Cross-rail race lost a receipt");
        Check(results.Count(r => r.Body.GetProperty("status").GetString() == "Activated") == 1, "Conflicting upgrade and old-tier renewal both applied");
        await using var db = Db();
        var u = await db.Users.SingleAsync(u => u.TelegramId == q.TelegramId);
        if (u.Plan == q.TargetPlan)
            Check(u.SubscriptionExpiry == q.SubscriptionExpiry, "Upgrade winner must preserve expiry");
        else Check(u.Plan == q.FromPlan && u.SubscriptionExpiry == q.SubscriptionExpiry.AddDays(30), "Renewal winner must retain its full 30 days");
        Check(u.EntitlementVersion == 1, "Race applied both state transitions");
        Check(await db.Payments.CountAsync(p => p.TelegramUserId == q.TelegramId) == 2, "Race lost ledger receipt");
        Check(await db.ActivityLogs.CountAsync(a => a.TelegramId == q.TelegramId && a.Action == "payment_completed" && a.Success) == 1, "Hold falsely audited as activation");
        Check(await db.ActivityLogs.CountAsync(a => a.TelegramId == q.TelegramId && a.Action == "payment_held" && !a.Success) == 1, "Race hold not audited");
    }
    public async Task ReceiptBinding(string rail)
    {
        foreach (var mode in new[] { "provider", "plan", "duration", "version", "expiry", "current-plan", "missing-quote" })
        {
            var q = await Quote(rail);
            var r = Receipt(q);
            var reason = "EntitlementChanged";
            await using var db = Db();
            if (mode == "provider") { r.Provider = rail == "ton" ? "telegram_stars" : "ton"; reason = "CurrencyMismatch"; }
            if (mode == "plan") { r.Plan = "Elite"; reason = "PlanMismatch"; }
            if (mode == "duration") { r.DurationDays = 30; reason = "UpgradeMustNotExtendDuration"; }
            if (mode == "version") await db.Users.Where(u => u.TelegramId == q.TelegramId).ExecuteUpdateAsync(s => s.SetProperty(u => u.EntitlementVersion, 1));
            if (mode == "expiry") await db.Users.Where(u => u.TelegramId == q.TelegramId).ExecuteUpdateAsync(s => s.SetProperty(u => u.SubscriptionExpiry, q.SubscriptionExpiry.AddDays(30)));
            if (mode == "current-plan") await db.Users.Where(u => u.TelegramId == q.TelegramId).ExecuteUpdateAsync(s => s.SetProperty(u => u.Plan, SubscriptionPlan.Elite));
            if (mode == "missing-quote") { r.QuoteReference = Guid.NewGuid().ToString("N"); reason = "QuoteUnavailable"; }
            await Held(await Complete(r), q, reason, q.ExpectedUnits);
        }
    }
    public IEnumerable<(string Name, Func<Task> Run)> Cases()
    {
        yield return ("upgrade migration rollback/reapply preserves legacy entitlements", Migration);
        yield return ("exact proration across every tier pair and fractional/minimum/extended durations", Pricing);
        foreach (var rail in new[] { "ton", "telegram_stars" })
        {
            yield return ($"{rail}: renewal billing-period allow-list and replay", () => RenewalPeriods(rail));
            yield return ($"{rail}: upgrade activation preserves expiry and replays once", () => Activation(rail));
            yield return ($"{rail}: one-unit underpayment held durably", () => Mismatch(rail, -1));
            yield return ($"{rail}: one-unit overpayment held durably", () => Mismatch(rail, 1));
            yield return ($"{rail}: renewal invalidates quote", () => StateConflict(rail));
            yield return ($"{rail}: payment timestamp and delayed delivery", () => PaymentWindow(rail));
            yield return ($"{rail}: quote and duplicate user isolation", () => Authorization(rail));
            yield return ($"{rail}: rollback after activation SQL and retry", () => Rollback(rail, false));
            yield return ($"{rail}: rollback after reconciliation SQL and retry", () => Rollback(rail, true));
            yield return ($"{rail}: concurrent duplicate upgrade receipt", () => Concurrent(rail, true));
            yield return ($"{rail}: concurrent distinct receipts for one quote", () => Concurrent(rail, false));
            yield return ($"{rail}: concurrent separate quotes", () => SeparateQuotes(rail));
            yield return ($"{rail}: concurrent cross-rail quotes", () => SeparateQuotes(rail, true));
            yield return ($"{rail}: upgrade versus cross-rail renewal", () => RenewalRace(rail));
            yield return ($"{rail}: currency/plan/duration/state binding", () => ReceiptBinding(rail));
        }
    }
}

sealed class FailAfterUpgradeSave : SaveChangesInterceptor
{
    public bool Triggered { get; private set; }
    public override ValueTask<int> SavedChangesAsync(SaveChangesCompletedEventData eventData, int result, CancellationToken cancellationToken = default)
    {
        Triggered = true;
        throw new DbUpdateException("Injected after SQL writes but before transaction commit");
    }
}

// Force both independent connections to reach the contended PostgreSQL user
// lock before either proceeds; concurrency tests must not pass by running serially.
sealed class UpgradeLockBarrier : DbCommandInterceptor
{
    private int arrivals;
    private readonly TaskCompletionSource ready = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public override async ValueTask<InterceptionResult<DbDataReader>> ReaderExecutingAsync(
        DbCommand command, CommandEventData eventData, InterceptionResult<DbDataReader> result,
        CancellationToken cancellationToken = default)
    {
        if (command.CommandText.Contains("FROM \"Users\"") && command.CommandText.Contains("FOR UPDATE"))
        {
            if (Interlocked.Increment(ref arrivals) == 2) ready.TrySetResult();
            await ready.Task.WaitAsync(TimeSpan.FromSeconds(30), cancellationToken);
        }
        return result;
    }
}
