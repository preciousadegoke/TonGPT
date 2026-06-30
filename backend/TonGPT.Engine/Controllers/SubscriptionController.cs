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

        // NOTE: the POST "upgrade" endpoint was REMOVED (PAY-002/PAY-003/DATA-001).
        // It was an amount-blind, TOCTOU-racy second activation path whose
        // idempotency relied on a slow, poisonable substring scan of ActivityLogs.
        // The single canonical activation path is now POST api/Payment/complete,
        // which validates the paid amount and uses the (ExternalId, Provider)
        // unique index as the one idempotency authority. This controller now only
        // exposes read-only status.
    }
}
