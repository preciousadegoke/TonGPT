using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using TonGPT.Engine.Data;
using TonGPT.Engine.Models;

namespace TonGPT.Engine.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class PaymentController : ControllerBase
    {
        private readonly AppDbContext _context;
        private readonly ILogger<PaymentController> _logger;

        public PaymentController(AppDbContext context, ILogger<PaymentController> logger)
        {
            _context = context;
            _logger = logger;
        }

        // ================================================================
        // ATOMIC RECORD + ACTIVATE — the ONE canonical activation path.
        // ----------------------------------------------------------------
        // Records the payment AND activates the subscription in ONE database
        // transaction. The unique index on (ExternalId, Provider) is the single
        // idempotency authority: a replayed webhook can never double-activate.
        //
        // The Engine validates the PAID AMOUNT against the canonical price here
        // (PAY-001), so activation can never be granted for free or underpayment
        // — even by a direct caller holding the API key. The old amount-blind
        // /record + /Subscription/upgrade endpoints have been removed.
        // ================================================================
        public class CompletePaymentRequest
        {
            public required string TelegramId { get; set; }
            public required string Plan { get; set; }       // engine plan name: Starter/Pro/ProPlus/Elite
            public required string Provider { get; set; }   // "ton" | "ton_manual" | "telegram_stars"
            public string? ExternalId { get; set; }         // provider charge/tx id (idempotency key)
            public int DurationDays { get; set; } = 30;
            public decimal AmountTon { get; set; } = 0m;    // paid TON (for ton* providers)
            public long AmountStars { get; set; } = 0;      // paid Stars (for telegram_stars)
            [System.ComponentModel.DataAnnotations.MaxLength(128)]
            public string? CheckoutReference { get; set; }
        }

        [HttpPost("complete")]
        public async Task<IActionResult> Complete([FromBody] CompletePaymentRequest request)
        {
            if (string.IsNullOrWhiteSpace(request.TelegramId)
                || string.IsNullOrWhiteSpace(request.Plan)
                || string.IsNullOrWhiteSpace(request.Provider))
            {
                return BadRequest(new { message = "TelegramId, Plan and Provider are required." });
            }

            // ExternalId is the idempotency key — REQUIRED for paid activations so a
            // missing id can never bypass dedup (PAY-005/PAY-006).
            if (string.IsNullOrEmpty(request.ExternalId))
            {
                return BadRequest(new { message = "ExternalId is required." });
            }

            // Reject unknown / numeric / Free plans up front (4xx => no retry/queue).
            if (!Enum.TryParse<SubscriptionPlan>(request.Plan, ignoreCase: true, out var plan)
                || !Enum.IsDefined(typeof(SubscriptionPlan), plan)
                || plan == SubscriptionPlan.Free)
            {
                return BadRequest(new { message = $"Invalid plan: {request.Plan}" });
            }

            var durationDays = request.DurationDays > 0 ? request.DurationDays : 30;
            var now = DateTime.UtcNow;

            // ---- Fast idempotency pre-check (cheap, avoids building state) ----
            // Done BEFORE amount validation so a legitimate retry of an
            // already-activated payment always returns success.
            {
                var dup = await _context.Payments.FirstOrDefaultAsync(
                    p => p.ExternalId == request.ExternalId && p.Provider == request.Provider);
                if (dup != null)
                {
                    var existingUser = await _context.Users
                        .FirstOrDefaultAsync(x => x.TelegramId == request.TelegramId);
                    _logger.LogInformation(
                        "Payment/complete idempotent hit for ExternalId {ExternalId}.", request.ExternalId);
                    return Ok(new
                    {
                        status = "AlreadyProcessed",
                        alreadyProcessed = true,
                        paymentId = dup.Id,
                        plan = (existingUser?.Plan ?? SubscriptionPlan.Free).ToString(),
                        expiry = existingUser?.SubscriptionExpiry
                    });
                }
            }

            // ---- Authoritative amount validation (PAY-001) ----
            // The ENGINE — not the caller — decides whether enough was paid, using
            // the canonical core/pricing.py values mirrored in Pricing.cs. This is a
            // NEW payment (not a duplicate), so an underpayment is a hard 4xx the
            // caller must not retry. Returns 4xx => engine_client treats it as
            // permanent (no queue), so a genuine underpayment is surfaced, not looped.
            if (!Pricing.TryGet(plan, out var price))
            {
                return BadRequest(new { message = $"No price configured for plan {plan}." });
            }
            var provider = request.Provider.Trim().ToLowerInvariant();
            if (provider == "telegram_stars")
            {
                if (request.AmountStars < price.Stars)
                {
                    _logger.LogWarning("Underpaid Stars: user {TelegramId} paid {Paid} < {Expected} for {Plan}",
                        request.TelegramId, request.AmountStars, price.Stars, plan);
                    return BadRequest(new { message = $"Underpayment: {request.AmountStars} < {price.Stars} Stars." });
                }
            }
            else if (provider == "ton" || provider == "ton_manual")
            {
                // Accept overpayment; allow a small tolerance under to match the
                // on-chain monitor so we never reject a transfer it already accepted.
                if (request.AmountTon < price.Ton * (1m - Pricing.TonTolerance))
                {
                    _logger.LogWarning("Underpaid TON: user {TelegramId} paid {Paid} < {Expected} for {Plan}",
                        request.TelegramId, request.AmountTon, price.Ton, plan);
                    return BadRequest(new { message = $"Underpayment: {request.AmountTon} < {price.Ton} TON." });
                }
            }
            else
            {
                // Fail closed on any provider we can't price-check.
                return BadRequest(new { message = $"Unknown payment provider: {request.Provider}." });
            }

            // ---- Build payment + activation, commit atomically ----
            var user = await _context.Users.FirstOrDefaultAsync(u => u.TelegramId == request.TelegramId);
            if (user == null)
            {
                user = new User { TelegramId = request.TelegramId };
                _context.Users.Add(user);
            }

            var payment = new Payment
            {
                Id = Guid.NewGuid(),
                TelegramUserId = request.TelegramId,
                AmountTon = request.AmountTon,
                TransactionHash = request.ExternalId,
                Status = "Completed",
                Plan = request.Plan,
                Provider = request.Provider,
                ExternalId = request.ExternalId,
                CheckoutReference = request.CheckoutReference,
                CreatedAt = now
            };
            _context.Payments.Add(payment);

            _context.ActivityLogs.Add(new ActivityLog
            {
                TelegramId = request.TelegramId,
                Action = "payment_completed",
                Metadata = System.Text.Json.JsonSerializer.Serialize(new
                {
                    Plan = request.Plan,
                    Provider = request.Provider,
                    PaymentId = payment.Id,
                    DurationDays = durationDays
                }),
                Success = true,
                Timestamp = now
            });

            try
            {
                // SaveChanges and ExecuteUpdate must share a transaction: no
                // payment/audit may commit without its subscription extension.
                // Dispose rolls back before the catch queries for a duplicate.
                await using var transaction = await _context.Database.BeginTransactionAsync();
                await _context.SaveChangesAsync();

                // Compute from the current database value, not the earlier
                // tracked read. PostgreSQL serializes updates to this user so
                // concurrent distinct payments each add their full duration.
                var updated = await _context.Users
                    .Where(u => u.TelegramId == request.TelegramId)
                    .ExecuteUpdateAsync(setters => setters
                        .SetProperty(u => u.Plan, plan)
                        .SetProperty(u => u.SubscriptionExpiry, u =>
                            (u.SubscriptionExpiry.HasValue && u.SubscriptionExpiry.Value > now
                                ? u.SubscriptionExpiry.Value : now).AddDays(durationDays)));
                if (updated != 1)
                    throw new DbUpdateException("Payment activation requires exactly one user update.");

                // ExecuteUpdate bypasses tracked entities. Read the result while
                // this transaction still holds the user lock for the response.
                await _context.Entry(user).ReloadAsync();
                await transaction.CommitAsync();
            }
            catch (DbUpdateException ex)
            {
                // A failed save may be a payment duplicate, a concurrent user
                // creation, or another write failure. Confirm the payment first.
                foreach (var entry in _context.ChangeTracker.Entries().ToList())
                    entry.State = Microsoft.EntityFrameworkCore.EntityState.Detached;

                var existing = !string.IsNullOrEmpty(request.ExternalId)
                    ? await _context.Payments.FirstOrDefaultAsync(
                        p => p.ExternalId == request.ExternalId && p.Provider == request.Provider)
                    : null;
                if (existing == null)
                {
                    _logger.LogWarning(ex,
                        "Payment/complete write failed without a confirmed payment for ExternalId {ExternalId}, Provider {Provider}; retry required.",
                        request.ExternalId, request.Provider);
                    return StatusCode(StatusCodes.Status503ServiceUnavailable, new
                    {
                        status = "RetryableFailure",
                        retryable = true,
                        message = "Payment was not confirmed. Retry with the same ExternalId and Provider."
                    });
                }

                var u1 = await _context.Users.FirstOrDefaultAsync(x => x.TelegramId == request.TelegramId);
                _logger.LogInformation(
                    "Payment/complete concurrent duplicate resolved for ExternalId {ExternalId}.",
                    request.ExternalId);
                return Ok(new
                {
                    status = "AlreadyProcessed",
                    alreadyProcessed = true,
                    paymentId = existing.Id,
                    plan = (u1?.Plan ?? SubscriptionPlan.Free).ToString(),
                    expiry = u1?.SubscriptionExpiry
                });
            }

            _logger.LogInformation(
                "Payment/complete activated user {TelegramId} -> {Plan} until {Expiry} (payment {PaymentId})",
                request.TelegramId, plan, user.SubscriptionExpiry, payment.Id);

            return Ok(new
            {
                status = "Activated",
                alreadyProcessed = false,
                paymentId = payment.Id,
                plan = plan.ToString(),
                expiry = user.SubscriptionExpiry
            });
        }
    }
}
