using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using TonGPT.Engine.Data;
using TonGPT.Engine.Models;

namespace TonGPT.Engine.Controllers;

[ApiController]
[Route("api/Checkout")]
public partial class CheckoutController(AppDbContext db, IConfiguration config) : ControllerBase
{
    // API-key middleware also applies. Unlike older controllers, missing signing
    // configuration NEVER falls back to API-key-only access.
    [HttpGet("status/{reference}")]
    public async Task<IActionResult> Status(string reference)
    {
        var secret = config["WalletLinkSigningSecret"]
            ?? Environment.GetEnvironmentVariable("WALLET_LINK_SIGNING_SECRET");
        if (string.IsNullOrWhiteSpace(secret))
            return StatusCode(503, new { message = "Checkout authorization is not configured." });
        if (reference.Length is < 1 or > 128) return BadRequest();
        var parts = Request.Headers["X-Checkout-Assertion"].ToString().Split('|');
        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        if (parts.Length != 6 || parts[0] != "co1" || parts[2] != reference
            || !long.TryParse(parts[1], out var userId) || userId <= 0
            || !long.TryParse(parts[3], out var expiry) || expiry <= now || expiry > now + 120)
            return StatusCode(403);
        byte[] supplied;
        try { supplied = Convert.FromHexString(parts[5]); }
        catch (FormatException) { return StatusCode(403); }
        var body = string.Join('|', parts.Take(5));
        var expected = HMACSHA256.HashData(Encoding.UTF8.GetBytes(secret), Encoding.UTF8.GetBytes(body));
        if (!CryptographicOperations.FixedTimeEquals(expected, supplied)) return StatusCode(403);

        Response.Headers.CacheControl = "no-store";
        var payment = await db.Payments.AsNoTracking()
            .Where(p => p.TelegramUserId == parts[1] && p.CheckoutReference == reference)
            .OrderByDescending(p => p.CreatedAt).FirstOrDefaultAsync();
        if (payment == null) return Ok(new { status = "pending" });
        if (payment.Status == "ReconciliationRequired") return Ok(new { status = "reconciliation_required", paymentId = payment.Id });
        if (payment.Status != "Completed") return Ok(new { status = "pending" });
        var user = await db.Users.AsNoTracking().SingleOrDefaultAsync(u => u.TelegramId == parts[1]);
        var quote = await db.UpgradeQuotes.AsNoTracking().SingleOrDefaultAsync(q => q.AppliedPaymentId == payment.Id);
        if (quote?.Kind == "downgrade") return Ok(new {
            status = "scheduled", paymentId = payment.Id, scheduledPlan = payment.Plan,
            scheduledStart = user?.PendingStartsAt, scheduledExpiry = user?.PendingExpiry,
        });
        var effective = Services.EffectiveEntitlement.Resolve(user, DateTime.UtcNow);
        var active = effective.Plan != SubscriptionPlan.Free;
        return Ok(new {
            status = "activated", paymentId = payment.Id,
            plan = effective.Plan.ToString(), expiry = effective.Expiry,
            entitlementActive = active,
        });
    }
}
