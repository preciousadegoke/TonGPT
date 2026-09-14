using System.Text.Json;
using System.Data.Common;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.Logging.Abstractions;
using Npgsql;
using TonGPT.Engine.Controllers;
using TonGPT.Engine.Data;
using TonGPT.Engine.Models;
using static TonGPT.Engine.Controllers.PaymentController;

// Executable integration suite: no additional test-framework packages needed.
// The Python runner supplies a newly created, disposable PostgreSQL container.
var connectionString = Environment.GetEnvironmentVariable("TONGPT_PAYMENT_TEST_DB")
    ?? throw new InvalidOperationException("Run scripts/test_payment_controller.py to create an isolated test database.");
var target = new NpgsqlConnectionStringBuilder(connectionString);
if (target.Host != "127.0.0.1" || target.Database?.StartsWith("tongpt_payment_tests_") != true)
    throw new InvalidOperationException("Refusing to run against a non-test database.");

AppDbContext Context(params IInterceptor[] interceptors) => new(
    new DbContextOptionsBuilder<AppDbContext>().UseNpgsql(connectionString)
        .AddInterceptors(interceptors).Options);

async Task<Reply> Complete(CompletePaymentRequest request, params IInterceptor[] interceptors)
{
    await using var db = Context(interceptors);
    var controller = new PaymentController(db, NullLogger<PaymentController>.Instance);
    var result = await controller.Complete(request);
    if (result is not ObjectResult response)
        throw new InvalidOperationException($"Unexpected response type: {result.GetType().Name}");
    return new Reply(response.StatusCode ?? 200, JsonSerializer.SerializeToElement(response.Value));
}

CompletePaymentRequest Request(string user, string externalId) => new()
{
    TelegramId = user, ExternalId = externalId, Provider = "ton", Plan = "Pro",
    AmountTon = 30m, DurationDays = 30
};

void Check(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
}

void Confirmed(Reply response, bool already)
{
    Check(response.Code == 200, $"Expected HTTP 200, got {response.Code}");
    Check(response.Body.GetProperty("alreadyProcessed").GetBoolean() == already, "Wrong duplicate result");
    Check(response.Body.GetProperty("paymentId").ValueKind == JsonValueKind.String,
        "Success must include a persisted payment ID");
    Check(response.Body.GetProperty("paymentId").GetGuid() != Guid.Empty, "Empty payment ID");
}

async Task Counts(string user, int payments, int users)
{
    await using var db = Context();
    Check(await db.Payments.CountAsync(p => p.TelegramUserId == user) == payments, "Wrong payment count");
    Check(await db.Users.CountAsync(u => u.TelegramId == user) == users, "Wrong user count");
    Check(await db.ActivityLogs.CountAsync(a => a.TelegramId == user && a.Action == "payment_completed") == payments,
        "Payment and activation audit must commit together");
}

async Task ConcurrentDuplicate()
{
    var user = "duplicate-" + Guid.NewGuid().ToString("N");
    var request = Request(user, "tx-" + user);
    var barrier = new ConcurrentSaveBarrier();
    var responses = await Task.WhenAll(Complete(request, barrier), Complete(request, barrier));
    Check(responses.Count(r => r.Body.GetProperty("alreadyProcessed").GetBoolean()) == 1,
        "Exactly one concurrent notification must be a duplicate");
    foreach (var response in responses)
        Confirmed(response, response.Body.GetProperty("alreadyProcessed").GetBoolean());
    Check(responses[0].Body.GetProperty("paymentId").GetGuid() == responses[1].Body.GetProperty("paymentId").GetGuid(),
        "Both notifications must identify the same durable payment");
    await Counts(user, 1, 1);
}

async Task ConcurrentNewUserPayments()
{
    var user = "new-user-" + Guid.NewGuid().ToString("N");
    var requests = new[] { Request(user, "tx-a-" + user), Request(user, "tx-b-" + user) };
    var barrier = new ConcurrentSaveBarrier();
    var responses = await Task.WhenAll(Complete(requests[0], barrier), Complete(requests[1], barrier));
    Check(responses.Count(r => r.Code == 200) == 1 && responses.Count(r => r.Code == 503) == 1,
        "Concurrent user creation: loser must be retryable HTTP 503, never false AlreadyProcessed");
    var loser = Array.FindIndex(responses, r => r.Code == 503);
    Check(responses[loser].Body.GetProperty("retryable").GetBoolean(), "Failure must explicitly be retryable");
    Confirmed(responses[1 - loser], false);
    await Counts(user, 1, 1);
    Confirmed(await Complete(requests[loser]), false);
    await Counts(user, 2, 1);

    await using var db = Context();
    var expiry = await db.Users.Where(u => u.TelegramId == user).Select(u => u.SubscriptionExpiry).SingleAsync();
    foreach (var request in requests) Confirmed(await Complete(request), true);
    var afterReplay = await db.Users.AsNoTracking().Where(u => u.TelegramId == user)
        .Select(u => u.SubscriptionExpiry).SingleAsync();
    Check(expiry == afterReplay, "Replaying either confirmed payment must not extend the subscription again");
    await Counts(user, 2, 1);
}

async Task PersistenceFailure()
{
    var user = "write-failure-" + Guid.NewGuid().ToString("N");
    var request = Request(user, "tx-" + user);
    var response = await Complete(request, new FailingSave());
    Check(response.Code == 503, "Unconfirmed DbUpdateException must return HTTP 503");
    Check(response.Body.GetProperty("retryable").GetBoolean(), "Failure must be retryable");
    await Counts(user, 0, 0);
    Confirmed(await Complete(request), false);
    Confirmed(await Complete(request), true);
    await Counts(user, 1, 1);
}

async Task ConcurrentRenewals(DateTime? initialExpiry)
{
    var user = "renewal-" + Guid.NewGuid().ToString("N");
    await using (var db = Context())
    {
        db.Users.Add(new User { TelegramId = user, SubscriptionExpiry = initialExpiry });
        await db.SaveChangesAsync();
    }
    var requests = new[] { Request(user, "ton-" + user), Request(user, "stars-" + user) };
    requests[1].Provider = "telegram_stars";
    requests[1].AmountStars = 100000;
    requests[1].DurationDays = 17;
    var started = DateTime.UtcNow;
    var barrier = new ConcurrentSaveBarrier();
    var responses = await Task.WhenAll(Complete(requests[0], barrier), Complete(requests[1], barrier));
    foreach (var response in responses) Confirmed(response, false);
    await using var check = Context();
    var saved = await check.Users.AsNoTracking().SingleAsync(u => u.TelegramId == user);
    if (initialExpiry > started)
        Check(saved.SubscriptionExpiry == initialExpiry.Value.AddDays(47), "Concurrent renewals must add BOTH durations to the existing expiry");
    else
        Check(saved.SubscriptionExpiry >= started.AddDays(47) && saved.SubscriptionExpiry <= DateTime.UtcNow.AddDays(47),
            "Expired/null subscriptions must receive BOTH durations from now");
    Check(saved.Plan == SubscriptionPlan.Pro, "Renewal must update the plan");
    Check(responses.Max(r => r.Body.GetProperty("expiry").GetDateTime()) == saved.SubscriptionExpiry,
        "Responses must reflect the database-computed expiry");
    foreach (var request in requests) Confirmed(await Complete(request), true);
    var afterReplay = await check.Users.AsNoTracking().SingleAsync(u => u.TelegramId == user);
    Check(afterReplay.SubscriptionExpiry == saved.SubscriptionExpiry, "Replaying renewals must not add time");
    await Counts(user, 2, 1);
}

async Task ConcurrentRenewalDuplicate()
{
    var user = "renewal-duplicate-" + Guid.NewGuid().ToString("N");
    var expiry = new DateTime(2035, 1, 1, 0, 0, 0, DateTimeKind.Utc);
    await using (var db = Context())
    {
        db.Users.Add(new User { TelegramId = user, SubscriptionExpiry = expiry });
        await db.SaveChangesAsync();
    }
    var request = Request(user, "tx-" + user);
    var barrier = new ConcurrentSaveBarrier();
    var responses = await Task.WhenAll(Complete(request, barrier), Complete(request, barrier));
    Check(responses.Count(r => r.Body.GetProperty("alreadyProcessed").GetBoolean()) == 1, "Exactly one duplicate expected");
    foreach (var response in responses) Confirmed(response, response.Body.GetProperty("alreadyProcessed").GetBoolean());
    await using var check = Context();
    Check((await check.Users.SingleAsync(u => u.TelegramId == user)).SubscriptionExpiry == expiry.AddDays(30),
        "Concurrent duplicate must extend only once");
    await Counts(user, 1, 1);
}

async Task RenewalRollback()
{
    var user = "renewal-rollback-" + Guid.NewGuid().ToString("N");
    var expiry = new DateTime(2035, 1, 1, 0, 0, 0, DateTimeKind.Utc);
    await using (var db = Context())
    {
        db.Users.Add(new User { TelegramId = user, SubscriptionExpiry = expiry });
        await db.SaveChangesAsync();
    }
    var request = Request(user, "tx-" + user);
    var failure = new FailAfterRenewalUpdate();
    var response = await Complete(request, failure);
    Check(failure.Triggered, "Failure must be injected AFTER the actual database expiry update");
    Check(response.Code == 503, "Rolled-back renewal must be retryable");
    await Counts(user, 0, 1);
    await using var check = Context();
    var saved = await check.Users.AsNoTracking().SingleAsync(u => u.TelegramId == user);
    Check(saved.SubscriptionExpiry == expiry && saved.Plan == SubscriptionPlan.Free, "Expiry and plan must roll back with payment/audit");
    Confirmed(await Complete(request), false);
    Confirmed(await Complete(request), true);
    Check((await check.Users.AsNoTracking().SingleAsync(u => u.TelegramId == user)).SubscriptionExpiry == expiry.AddDays(30),
        "Retry after rollback must extend exactly once");
    await Counts(user, 1, 1);
}

await using (var db = Context()) await CheckoutTests.Migration(db);
Console.WriteLine("PASS: checkout migration upgrade/rollback preserves legacy payments (disposable DB)");
var tests = new (string Name, Func<Task> Run)[]
{
    ("concurrent duplicate notification", ConcurrentDuplicate),
    ("concurrent new-user payments and replay", ConcurrentNewUserPayments),
    ("persistence failure without a matching payment", PersistenceFailure),
    ("concurrent TON/Stars renewals: future expiry", () => ConcurrentRenewals(new DateTime(2035, 1, 1, 0, 0, 0, DateTimeKind.Utc))),
    ("concurrent TON/Stars renewals: expired", () => ConcurrentRenewals(DateTime.UtcNow.AddDays(-1))),
    ("concurrent TON/Stars renewals: no expiry", () => ConcurrentRenewals(null)),
    ("concurrent duplicate renewal", ConcurrentRenewalDuplicate),
    ("rollback after renewal update and retry", RenewalRollback),
    ("checkout correlation and per-user authorization for TON/Stars", async () => {
        await using var db = Context();
        await CheckoutTests.AuthorizationAndCorrelation(db);
    })
};
var failures = 0;
foreach (var test in tests)
{
    try { await test.Run(); Console.WriteLine($"PASS: {test.Name}"); }
    catch (Exception error) { failures++; Console.WriteLine($"FAIL: {test.Name}: {error.Message}"); }
}
Console.WriteLine($"{tests.Length - failures}/{tests.Length} payment-controller integration tests passed");
return failures == 0 ? 0 : 1;

record Reply(int Code, JsonElement Body);

// Both requests must finish their initial reads before either writes. PostgreSQL
// then raises a real unique violation; this does not mock the EF exception path.
sealed class ConcurrentSaveBarrier : SaveChangesInterceptor
{
    private int arrivals;
    private readonly TaskCompletionSource bothArrived = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public override async ValueTask<InterceptionResult<int>> SavingChangesAsync(
        DbContextEventData eventData, InterceptionResult<int> result, CancellationToken cancellationToken = default)
    {
        if (Interlocked.Increment(ref arrivals) == 2) bothArrived.TrySetResult();
        await bothArrived.Task.WaitAsync(TimeSpan.FromSeconds(30), cancellationToken);
        return result;
    }
}

sealed class FailingSave : SaveChangesInterceptor
{
    public override ValueTask<InterceptionResult<int>> SavingChangesAsync(
        DbContextEventData eventData, InterceptionResult<int> result, CancellationToken cancellationToken = default)
        => throw new DbUpdateException("Simulated persistence failure before commit");
}

sealed class FailAfterRenewalUpdate : DbCommandInterceptor
{
    public bool Triggered { get; private set; }
    public override ValueTask<int> NonQueryExecutedAsync(DbCommand command, CommandExecutedEventData eventData,
        int result, CancellationToken cancellationToken = default)
    {
        if (command.CommandText.StartsWith("UPDATE \"Users\"", StringComparison.Ordinal))
        {
            Triggered = true;
            throw new DbUpdateException("Simulated failure after the renewal UPDATE, before commit");
        }
        return ValueTask.FromResult(result);
    }
}
