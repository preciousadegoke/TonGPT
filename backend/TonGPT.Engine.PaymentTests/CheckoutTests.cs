using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using TonGPT.Engine.Controllers;
using TonGPT.Engine.Data;

static class CheckoutTests
{
    const string Secret = "disposable-checkout-test-signing-secret";
    static void Check(bool ok, string message) { if (!ok) throw new Exception(message); }
    public static async Task Migration(AppDbContext db)
    {
        var migrator = db.GetService<IMigrator>();
        await migrator.MigrateAsync("20260305203732_AddConsentFields");
        var id = Guid.NewGuid();
        await db.Database.ExecuteSqlInterpolatedAsync($"INSERT INTO \"Payments\" (\"Id\", \"TelegramUserId\", \"AmountTon\", \"Status\", \"CreatedAt\") VALUES ({id}, 'legacy-checkout-test', 30, 'Completed', {DateTime.UtcNow})");
        await migrator.MigrateAsync();
        var old = await db.Payments.AsNoTracking().SingleAsync(p => p.Id == id);
        Check(old.CheckoutReference == null && old.AmountTon == 30m, "Migration changed an old payment");
        await migrator.MigrateAsync("20260305203732_AddConsentFields");
        await migrator.MigrateAsync();
        Check(await db.Payments.AnyAsync(p => p.Id == id), "Rollback/upgrade lost an old payment");
        Check(!db.Database.HasPendingModelChanges(), "Migration snapshot differs from the model");
    }

    static string Token(string user, string reference, long? expiry = null)
    {
        var body = $"co1|{user}|{reference}|{expiry ?? DateTimeOffset.UtcNow.ToUnixTimeSeconds() + 60}|testnonce";
        return body + "|" + Convert.ToHexString(HMACSHA256.HashData(Encoding.UTF8.GetBytes(Secret), Encoding.UTF8.GetBytes(body))).ToLowerInvariant();
    }
    static async Task<(int Code, JsonElement Body)> Read(AppDbContext db, string reference, string? token, string secret = Secret)
    {
        var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["WalletLinkSigningSecret"] = secret }).Build();
        var controller = new CheckoutController(db, config) { ControllerContext = new() { HttpContext = new DefaultHttpContext() } };
        if (token != null) controller.Request.Headers["X-Checkout-Assertion"] = token;
        var result = await controller.Status(reference);
        return result switch {
            ObjectResult value => (value.StatusCode ?? 200, JsonSerializer.SerializeToElement(value.Value)),
            StatusCodeResult code => (code.StatusCode, default),
            _ => throw new Exception("Unexpected checkout response"),
        };
    }
    public static async Task AuthorizationAndCorrelation(AppDbContext db)
    {
        foreach (var provider in new[] { "ton", "telegram_stars" })
        {
            var reference = Guid.NewGuid().ToString("N");
            var complete = new PaymentController(db, NullLogger<PaymentController>.Instance);
            var request = new PaymentController.CompletePaymentRequest {
                TelegramId = "777", Plan = "Pro", Provider = provider, ExternalId = Guid.NewGuid().ToString("N"),
                AmountTon = 30, AmountStars = 4000, CheckoutReference = reference,
            };
            Check((await Read(db, reference, Token("777", reference))).Body.GetProperty("status").GetString() == "pending", "New reference cannot inherit old entitlement");
            await complete.Complete(request);
            await complete.Complete(request);
            Check(await db.Payments.CountAsync(p => p.CheckoutReference == reference) == 1, "Reference changed provider idempotency");
            var own = await Read(db, reference, Token("777", reference));
            Check(own.Code == 200 && own.Body.GetProperty("status").GetString() == "activated" && own.Body.GetProperty("entitlementActive").GetBoolean(), "Own activation not confirmed");
            Check(own.Body.GetProperty("paymentId").GetGuid() != Guid.Empty, "Missing payment proof");
            Check((await Read(db, reference, null)).Code == 403, "API-key-only read allowed");
            Check((await Read(db, reference, Token("777", "different"))).Code == 403, "Reference substitution allowed");
            Check((await Read(db, reference, Token("777", reference, 1))).Code == 403, "Expired assertion allowed");
            Check((await Read(db, reference, Token("777", reference) + "00")).Code == 403, "Tampered assertion allowed");
            Check((await Read(db, reference, Token("777", reference), "")).Code == 503, "Missing secret failed open");
            var other = await Read(db, reference, Token("888", reference));
            Check(other.Code == 200 && other.Body.GetProperty("status").GetString() == "pending" && !other.Body.TryGetProperty("paymentId", out _), "Cross-user payment disclosure");
        }
    }
}
