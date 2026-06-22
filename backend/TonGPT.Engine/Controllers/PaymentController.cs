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

        public class RecordPaymentRequest
        {
            public required string TelegramId { get; set; }
            public required string Plan { get; set; }
            public required string Provider { get; set; }
            public string? ExternalId { get; set; }
        }

        /// <summary>
        /// Record a completed payment (e.g. after Telegram Stars success). Call this before Subscription/upgrade.
        /// Returns the Payment Id to pass as paymentRecordId when upgrading.
        /// </summary>
        [HttpPost("record")]
        public async Task<IActionResult> Record([FromBody] RecordPaymentRequest request)
        {
            if (!string.IsNullOrEmpty(request.ExternalId) && await _context.Payments.AnyAsync(p => p.ExternalId == request.ExternalId && p.Provider == request.Provider))
            {
                var existing = await _context.Payments.FirstAsync(p => p.ExternalId == request.ExternalId && p.Provider == request.Provider);
                _logger.LogInformation("Duplicate payment payload received for ExternalId {ExternalId}. Returning existing PaymentId.", request.ExternalId);
                return Ok(new { paymentId = existing.Id, status = "Already Recorded" });
            }

            var payment = new Payment
            {
                Id = Guid.NewGuid(),
                TelegramUserId = request.TelegramId,
                AmountTon = 0,
                TransactionHash = request.ExternalId,
                Status = "Completed",
                Plan = request.Plan,
                Provider = request.Provider,
                ExternalId = request.ExternalId,
                CreatedAt = DateTime.UtcNow
            };

            _context.Payments.Add(payment);

            try
            {
                await _context.SaveChangesAsync();
            }
            catch (DbUpdateException)
            {
                // Unique index violation — concurrent duplicate arrived between AnyAsync check and insert
                _context.Entry(payment).State = Microsoft.EntityFrameworkCore.EntityState.Detached;
                if (!string.IsNullOrEmpty(request.ExternalId))
                {
                    var existing = await _context.Payments.FirstOrDefaultAsync(p => p.ExternalId == request.ExternalId && p.Provider == request.Provider);
                    if (existing != null)
                    {
                        _logger.LogInformation("Concurrent duplicate resolved for ExternalId {ExternalId}.", request.ExternalId);
                        return Ok(new { paymentId = existing.Id, status = "Already Recorded" });
                    }
                }
                throw; // Re-throw if it's a different DB error
            }

            _logger.LogInformation("Payment recorded: {PaymentId} for plan {Plan} via {Provider}",
                payment.Id, request.Plan, request.Provider);

            return Ok(new { paymentId = payment.Id, status = "Recorded" });
        }

        // ================================================================
        // ATOMIC RECORD + ACTIVATE (P0 reliability fix)
        // ----------------------------------------------------------------
        // Records the payment AND activates the subscription in ONE database
        // transaction. The unique index on (ExternalId, Provider) is the single
        // idempotency authority: a replayed webhook can never double-activate.
        //
        // This is the canonical path used by the bot's successful_payment
        // handler. It replaces the old Redis-based idempotency claim, which
        // could lose a paid activation whenever Redis was down.
        // ================================================================
        public class CompletePaymentRequest
        {
            public required string TelegramId { get; set; }
            public required string Plan { get; set; }       // engine plan name: Starter/Pro/ProPlus/Elite
            public required string Provider { get; set; }   // e.g. telegram_stars
            public string? ExternalId { get; set; }         // Telegram charge id (idempotency key)
            public int DurationDays { get; set; } = 30;
            public decimal AmountTon { get; set; } = 0m;
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

            // Reject unknown plans up front (4xx => caller will NOT retry/queue).
            if (!Enum.TryParse<SubscriptionPlan>(request.Plan, ignoreCase: true, out var plan)
                || plan == SubscriptionPlan.Free)
            {
                return BadRequest(new { message = $"Invalid plan: {request.Plan}" });
            }

            var durationDays = request.DurationDays > 0 ? request.DurationDays : 30;
            var now = DateTime.UtcNow;

            // ---- Fast idempotency pre-check (cheap, avoids building state) ----
            if (!string.IsNullOrEmpty(request.ExternalId))
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
                CreatedAt = now
            };
            _context.Payments.Add(payment);

            // Extend from the later of (now, current expiry) so we never throw
            // away a user's remaining unexpired time on renewal.
            var basis = (user.SubscriptionExpiry.HasValue && user.SubscriptionExpiry.Value > now)
                ? user.SubscriptionExpiry.Value
                : now;
            user.Plan = plan;
            user.SubscriptionExpiry = basis.AddDays(durationDays);

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
                // ONE transaction: payment + user upgrade + audit log all commit
                // together, or none of them do.
                await _context.SaveChangesAsync();
            }
            catch (DbUpdateException)
            {
                // A concurrent duplicate slipped past the pre-check and tripped
                // the unique index. NOTHING was committed -> no double activation.
                foreach (var entry in _context.ChangeTracker.Entries().ToList())
                    entry.State = Microsoft.EntityFrameworkCore.EntityState.Detached;

                var existing = !string.IsNullOrEmpty(request.ExternalId)
                    ? await _context.Payments.FirstOrDefaultAsync(
                        p => p.ExternalId == request.ExternalId && p.Provider == request.Provider)
                    : null;
                var u1 = await _context.Users.FirstOrDefaultAsync(x => x.TelegramId == request.TelegramId);
                _logger.LogInformation(
                    "Payment/complete concurrent duplicate resolved for ExternalId {ExternalId}.",
                    request.ExternalId);
                return Ok(new
                {
                    status = "AlreadyProcessed",
                    alreadyProcessed = true,
                    paymentId = existing?.Id,
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
