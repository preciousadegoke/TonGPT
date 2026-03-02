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
                user.Plan = plan;
                user.SubscriptionExpiry = DateTime.UtcNow.AddDays(30);
                await _context.SaveChangesAsync();

                // Audit log
                _context.ActivityLogs.Add(new ActivityLog
                {
                    TelegramId = request.TelegramId,
                    Action = "subscription_upgrade",
                    Metadata = System.Text.Json.JsonSerializer.Serialize(new { Plan = request.Plan, PaymentId = payment.Id }),
                    Success = true,
                    Timestamp = DateTime.UtcNow
                });
                await _context.SaveChangesAsync();

                _logger.LogInformation("User {TelegramId} upgraded to {Plan} (payment {PaymentId})", request.TelegramId, request.Plan, payment.Id);
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
    }
}
