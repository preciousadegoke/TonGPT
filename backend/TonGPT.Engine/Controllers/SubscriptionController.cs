using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using TonGPT.Engine.Data;
using TonGPT.Engine.Models;

namespace TonGPT.Engine.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class SubscriptionController : ControllerBase
    {
        private readonly AppDbContext _context;
        private readonly ILogger<SubscriptionController> _logger;

        public SubscriptionController(AppDbContext context, ILogger<SubscriptionController> logger)
        {
            _context = context;
            _logger = logger;
        }

        [HttpGet("status/{telegramId}")]
        public async Task<IActionResult> GetStatus(string telegramId)
        {
            var user = await _context.Users.FirstOrDefaultAsync(u => u.TelegramId == telegramId);
            if (user == null)
            {
                return Ok(new { Plan = "Free", Expiry = (DateTime?)null });
            }
            return Ok(new { Plan = user.Plan.ToString(), Expiry = user.SubscriptionExpiry });
        }

        /// <summary>
        /// Upgrade user to a plan. Requires a valid paymentRecordId from a recent Payment/record call (payment verification).
        /// </summary>
        [HttpPost("upgrade")]
        public async Task<IActionResult> Upgrade([FromBody] UpgradeRequest request)
        {
            if (string.IsNullOrEmpty(request.TelegramId) || string.IsNullOrEmpty(request.Plan))
                return BadRequest("TelegramId and Plan are required.");

            // Payment verification: require a valid completed payment record for this user+plan
            if (!request.PaymentRecordId.HasValue)
            {
                _logger.LogWarning("Upgrade rejected: no PaymentRecordId for user {TelegramId}", request.TelegramId);
                return BadRequest("Payment verification required. Provide paymentRecordId from Payment/record.");
            }

            var payment = await _context.Payments
                .FirstOrDefaultAsync(p =>
                    p.Id == request.PaymentRecordId.Value &&
                    p.TelegramUserId == request.TelegramId &&
                    p.Status == "Completed" &&
                    p.Plan != null && string.Equals(p.Plan, request.Plan, StringComparison.OrdinalIgnoreCase) &&
                    p.CreatedAt > DateTime.UtcNow.AddHours(-24));

            if (payment == null)
            {
                _logger.LogWarning("Upgrade rejected: invalid or expired payment record for user {TelegramId} plan {Plan}",
                    request.TelegramId, request.Plan);
                return BadRequest("Invalid or expired payment record. Complete payment and use the returned paymentId.");
            }

            var user = await _context.Users.FirstOrDefaultAsync(u => u.TelegramId == request.TelegramId);
            if (user == null)
            {
                user = new User { TelegramId = request.TelegramId };
                _context.Users.Add(user);
            }

            if (Enum.TryParse<SubscriptionPlan>(request.Plan, true, out var plan))
            {
                var now = DateTime.UtcNow;
                var paymentIdStr = payment.Id.ToString();

                // IDEMPOTENCY: if this exact payment was already applied, return
                // success WITHOUT extending the subscription again. Makes the
                // endpoint safe to retry (e.g. background reconciliation).
                var alreadyApplied = await _context.ActivityLogs.AnyAsync(a =>
                    a.Action == "subscription_upgrade" &&
                    a.Metadata != null &&
                    a.Metadata.Contains(paymentIdStr));
                if (alreadyApplied)
                {
                    _logger.LogInformation(
                        "Upgrade idempotent: payment {PaymentId} already applied for user {TelegramId}.",
                        payment.Id, request.TelegramId);
                    return Ok(new { Status = "Success", NewPlan = user.Plan.ToString(), idempotent = true });
                }

                var durationDays = request.DurationDays > 0 ? request.DurationDays : 30;
                // Extend from the later of (now, current expiry) to preserve unexpired time.
                var basis = (user.SubscriptionExpiry.HasValue && user.SubscriptionExpiry.Value > now)
                    ? user.SubscriptionExpiry.Value
                    : now;
                user.Plan = plan;
                user.SubscriptionExpiry = basis.AddDays(durationDays);

                _context.ActivityLogs.Add(new ActivityLog
                {
                    TelegramId = request.TelegramId,
                    Action = "subscription_upgrade",
                    Metadata = System.Text.Json.JsonSerializer.Serialize(new { Plan = request.Plan, PaymentId = payment.Id, DurationDays = durationDays }),
                    Success = true,
                    Timestamp = now
                });

                // Single SaveChanges => user upgrade + audit log commit atomically.
                await _context.SaveChangesAsync();

                _logger.LogInformation("User {TelegramId} upgraded to {Plan} until {Expiry} (payment {PaymentId})",
                    request.TelegramId, request.Plan, user.SubscriptionExpiry, payment.Id);
                return Ok(new { Status = "Success", NewPlan = plan.ToString() });
            }

            return BadRequest("Invalid Plan");
        }
    }

    public class UpgradeRequest
    {
        public required string TelegramId { get; set; }
        public required string Plan { get; set; }
        /// <summary>Required. Guid from POST api/Payment/record response (paymentId).</summary>
        public Guid? PaymentRecordId { get; set; }
        /// <summary>Subscription length in days. Defaults to 30 when omitted.</summary>
        public int DurationDays { get; set; } = 30;
    }
}
