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

            _logger.LogInformation("Payment recorded: {PaymentId} for user {TelegramId} plan {Plan} provider {Provider}",
                payment.Id, request.TelegramId, request.Plan, request.Provider);

            return Ok(new { paymentId = payment.Id, status = "Recorded" });
        }
    }
}
