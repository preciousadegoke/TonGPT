using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using TonGPT.Engine.Models;
using TonGPT.Engine.Services;

namespace TonGPT.Engine.Controllers;

public partial class CheckoutController
{
    public record QuoteRequest(string Plan, string Provider);
    private (string? User, IActionResult? Error) AuthorizeQuote(string reference)
    {
        var secret = config["WalletLinkSigningSecret"] ?? Environment.GetEnvironmentVariable("WALLET_LINK_SIGNING_SECRET");
        if (string.IsNullOrWhiteSpace(secret)) return (null, StatusCode(503));
        if (!Guid.TryParseExact(reference, "N", out _)) return (null, BadRequest());
        var parts = Request.Headers["X-Checkout-Assertion"].ToString().Split('|');
        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        if (parts.Length != 6 || parts[0] != "co1" || parts[2] != reference
            || !long.TryParse(parts[1], out var userId) || userId <= 0
            || !long.TryParse(parts[3], out var expiry) || expiry <= now || expiry > now + 120)
            return (null, StatusCode(403));
        byte[] supplied;
        try { supplied = Convert.FromHexString(parts[5]); } catch (FormatException) { return (null, StatusCode(403)); }
        var expected = HMACSHA256.HashData(Encoding.UTF8.GetBytes(secret), Encoding.UTF8.GetBytes(string.Join('|', parts.Take(5))));
        if (!CryptographicOperations.FixedTimeEquals(expected, supplied)) return (null, StatusCode(403));
        Response.Headers.CacheControl = "no-store";
        return (parts[1], null);
    }

    private static object QuoteBody(UpgradeQuote quote) => new {
        kind = quote.Kind, reference = quote.Reference, expectedUnits = quote.ExpectedUnits.ToString(),
        expiry = quote.SubscriptionExpiry, validUntil = new DateTimeOffset(quote.ValidUntil).ToUnixTimeSeconds(),
        fromPlan = quote.FromPlan.ToString(), targetPlan = quote.TargetPlan.ToString(), provider = quote.Provider,
        scheduledStart = quote.Kind == "downgrade" ? quote.SubscriptionExpiry : (DateTime?)null,
        scheduledExpiry = quote.Kind == "downgrade" ? (quote.PendingStartsAt > quote.CreatedAt ? quote.PendingExpiry ?? quote.SubscriptionExpiry : quote.SubscriptionExpiry).AddDays(UpgradePricing.CycleDays) : (DateTime?)null,
    };

    [HttpPost("quote/{reference}")]
    public async Task<IActionResult> Quote(string reference, QuoteRequest request)
    {
        var auth = AuthorizeQuote(reference);
        if (auth.Error != null) return auth.Error;
        var name = Enum.GetNames<SubscriptionPlan>().FirstOrDefault(n => string.Equals(n, request.Plan, StringComparison.OrdinalIgnoreCase));
        if (name == null || name == "Free" || request.Provider is not ("ton" or "telegram_stars")) return BadRequest();
        var target = Enum.Parse<SubscriptionPlan>(name);
        var now = DateTimeOffset.FromUnixTimeSeconds(DateTimeOffset.UtcNow.ToUnixTimeSeconds()).UtcDateTime;
        var user = await db.Users.AsNoTracking().SingleOrDefaultAsync(u => u.TelegramId == auth.User);
        var effective = EffectiveEntitlement.Resolve(user, now);
        if (effective.Plan == SubscriptionPlan.Free || effective.Plan == target) return Ok(new { kind = "cycle" });
        var downgrade = target < effective.Plan;
        if (downgrade && effective.PendingPlan != null && effective.PendingPlan != target)
            return Conflict(new { message = "A different prepaid downgrade already exists. Contact support; no payment requested." });
        var existing = await db.UpgradeQuotes.AsNoTracking().SingleOrDefaultAsync(q => q.Reference == reference);
        if (existing != null)
        {
            if (existing.TelegramId != auth.User || existing.TargetPlan != target || existing.Provider != request.Provider)
                return Conflict();
            return Ok(QuoteBody(existing));
        }
        var quote = new UpgradeQuote {
            Reference = reference, TelegramId = auth.User!, FromPlan = effective.Plan, TargetPlan = target,
            SubscriptionExpiry = effective.Expiry!.Value, EntitlementVersion = user!.EntitlementVersion,
            Kind = downgrade ? "downgrade" : "upgrade", PendingPlan = user.PendingPlan,
            PendingStartsAt = user.PendingStartsAt, PendingExpiry = user.PendingExpiry,
            Provider = request.Provider, CreatedAt = now,
            ValidUntil = effective.Expiry.Value < now.AddMinutes(5) ? effective.Expiry.Value : now.AddMinutes(5),
            ExpectedUnits = downgrade ? CyclePrice(target, request.Provider)
                : UpgradePricing.Units(effective.Plan, target, request.Provider, effective.Expiry.Value - now),
        };
        db.UpgradeQuotes.Add(quote);
        await db.SaveChangesAsync();
        return Ok(QuoteBody(quote));
    }

    [HttpGet("validate/{reference}")]
    public async Task<IActionResult> ValidateQuote(string reference)
    {
        var auth = AuthorizeQuote(reference);
        if (auth.Error != null) return auth.Error;
        var quote = await db.UpgradeQuotes.AsNoTracking().SingleOrDefaultAsync(q => q.Reference == reference && q.TelegramId == auth.User);
        if (quote == null) return NotFound();
        var user = await db.Users.AsNoTracking().SingleOrDefaultAsync(u => u.TelegramId == auth.User);
        if (quote.ValidUntil <= DateTime.UtcNow || quote.AppliedPaymentId != null
            || !EffectiveEntitlement.Matches(user, quote, DateTime.UtcNow))
            return Conflict(new { message = "Quote expired or subscription changed. Request a new quote before paying." });
        return Ok(QuoteBody(quote));
    }

    private static long CyclePrice(SubscriptionPlan plan, string provider)
    {
        if (!Pricing.TryGet(plan, out var price)) throw new InvalidOperationException("Missing cycle price");
        return provider == "ton" ? checked((long)(price.Ton * 1_000_000_000m)) : price.Stars;
    }
}
