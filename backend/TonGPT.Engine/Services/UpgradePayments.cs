using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using TonGPT.Engine.Controllers;
using TonGPT.Engine.Data;
using TonGPT.Engine.Models;

namespace TonGPT.Engine.Services;

public class UpgradePayments(AppDbContext db, ILogger logger)
{
    public static IActionResult Held(Payment payment, bool already) => new OkObjectResult(new {
        status = "ReconciliationRequired", held = true, alreadyProcessed = already,
        paymentId = payment.Id, message = "Payment recorded for reconciliation; entitlement unchanged. Do not pay again.",
    });

    async Task<IActionResult> Replay(Payment payment, string userId)
    {
        if (payment.TelegramUserId != userId)
            return new ConflictObjectResult(new { message = "Payment identifier conflict." });
        if (payment.Status == "ReconciliationRequired") return Held(payment, true);
        var user = await db.Users.AsNoTracking().SingleOrDefaultAsync(u => u.TelegramId == userId);
        return new OkObjectResult(new { status = "AlreadyProcessed", alreadyProcessed = true, paymentId = payment.Id,
            plan = user?.Plan.ToString(), expiry = user?.SubscriptionExpiry });
    }

    public async Task<IActionResult> Complete(PaymentController.CompletePaymentRequest request)
    {
        if (string.IsNullOrWhiteSpace(request.TelegramId) || string.IsNullOrWhiteSpace(request.ExternalId)
            || string.IsNullOrWhiteSpace(request.Provider) || request.PaidUnits is null or < 0)
            return new BadRequestObjectResult(new { message = "Quoted receipts require user, provider, external ID and actual paid units." });
        var provider = request.Provider.Trim().ToLowerInvariant();
        if (provider is not ("ton" or "telegram_stars"))
            return new BadRequestObjectResult(new { message = "Unsupported quoted payment provider." });
        try
        {
            await using var transaction = await db.Database.BeginTransactionAsync();
            // The user lock is shared with ordinary renewals. A quote lock also
            // prevents a second distinct payment from applying the same upgrade.
            var user = await db.Users.FromSqlInterpolated(
                $"SELECT * FROM \"Users\" WHERE \"TelegramId\" = {request.TelegramId} FOR UPDATE").SingleOrDefaultAsync();
            var duplicate = await db.Payments.AsNoTracking().FirstOrDefaultAsync(p => p.ExternalId == request.ExternalId && p.Provider == provider);
            if (duplicate != null) return await Replay(duplicate, request.TelegramId);
            var quote = await db.UpgradeQuotes.FromSqlInterpolated(
                $"SELECT * FROM \"UpgradeQuotes\" WHERE \"Reference\" = {request.QuoteReference} FOR UPDATE").SingleOrDefaultAsync();
            var ownQuote = quote != null && quote.TelegramId == request.TelegramId;
            var reason = !ownQuote ? "QuoteUnavailable"
                : provider != quote!.Provider ? "CurrencyMismatch"
                : request.PaidUnits != quote.ExpectedUnits ? "AmountMismatch"
                : !string.Equals(request.Plan, quote.TargetPlan.ToString(), StringComparison.OrdinalIgnoreCase) ? "PlanMismatch"
                : request.DurationDays != 0 ? "UpgradeMustNotExtendDuration"
                : request.PaidAt == null ? "MissingPaymentTimestamp"
                : request.PaidAt < quote.CreatedAt || request.PaidAt > quote.ValidUntil || request.PaidAt > DateTime.UtcNow.AddMinutes(1) ? "PaymentOutsideQuoteWindow"
                : quote.AppliedPaymentId != null ? "QuoteAlreadyApplied"
                : user == null || user.Plan != quote.FromPlan || user.SubscriptionExpiry != quote.SubscriptionExpiry
                    || user.EntitlementVersion != quote.EntitlementVersion ? "EntitlementChanged"
                : null;
            var payment = new Payment {
                Id = Guid.NewGuid(), TelegramUserId = request.TelegramId, ExternalId = request.ExternalId,
                TransactionHash = request.ExternalId, Provider = provider,
                CheckoutReference = request.QuoteReference, Plan = ownQuote ? quote!.TargetPlan.ToString() : request.Plan,
                AmountTon = provider == "ton" ? request.PaidUnits.Value / 1_000_000_000m : 0,
                Status = reason == null ? "Completed" : "ReconciliationRequired", CreatedAt = DateTime.UtcNow,
            };
            db.Payments.Add(payment);
            if (reason != null)
                db.PaymentReconciliations.Add(new PaymentReconciliation {
                    PaymentId = payment.Id, QuoteReference = request.QuoteReference, Reason = reason,
                    Currency = provider == "ton" ? "TON" : "XTR", ActualUnits = request.PaidUnits.Value,
                    ExpectedUnits = ownQuote && provider == quote!.Provider ? quote.ExpectedUnits : null, PaidAt = request.PaidAt,
                });
            else
            {
                user!.Plan = quote!.TargetPlan;
                user.EntitlementVersion++;
                // Delayed notification does not change the already quoted expiry.
                quote.AppliedPaymentId = payment.Id;
            }
            db.ActivityLogs.Add(new ActivityLog {
                TelegramId = request.TelegramId, Action = reason == null ? "payment_completed" : "payment_held",
                Success = reason == null, Timestamp = DateTime.UtcNow,
                Metadata = System.Text.Json.JsonSerializer.Serialize(new { payment.Id, request.QuoteReference, reason }),
            });
            await db.SaveChangesAsync();
            await transaction.CommitAsync();
            if (reason != null)
            {
                logger.LogWarning("upgrade_payment_held payment={PaymentId} reason={Reason}", payment.Id, reason);
                return Held(payment, false);
            }
            logger.LogInformation("upgrade_payment_activated payment={PaymentId} expiry={Expiry}", payment.Id, user!.SubscriptionExpiry);
            return new OkObjectResult(new { status = "Activated", alreadyProcessed = false, paymentId = payment.Id,
                plan = user.Plan.ToString(), expiry = user.SubscriptionExpiry });
        }
        catch (DbUpdateException ex)
        {
            db.ChangeTracker.Clear();
            var duplicate = await db.Payments.AsNoTracking().FirstOrDefaultAsync(p => p.ExternalId == request.ExternalId && p.Provider == provider);
            if (duplicate != null) return await Replay(duplicate, request.TelegramId);
            logger.LogWarning(ex, "Quoted payment was not persisted; retry the same receipt.");
            return new ObjectResult(new { status = "RetryableFailure", retryable = true }) { StatusCode = 503 };
        }
    }
}
