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

        public SubscriptionController(AppDbContext context)
        {
            _context = context;
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

        [HttpPost("upgrade")]
        public async Task<IActionResult> Upgrade([FromBody] UpgradeRequest request)
        {
            var user = await _context.Users.FirstOrDefaultAsync(u => u.TelegramId == request.TelegramId);
            if (user == null)
            {
                user = new User { TelegramId = request.TelegramId };
                _context.Users.Add(user);
            }

            if (Enum.TryParse<SubscriptionPlan>(request.Plan, out var plan))
            {
                user.Plan = plan;
                user.SubscriptionExpiry = DateTime.UtcNow.AddDays(30);
                await _context.SaveChangesAsync();
                return Ok(new { Status = "Success", NewPlan = plan.ToString() });
            }

            return BadRequest("Invalid Plan");
        }
    }

    public class UpgradeRequest
    {
        public required string TelegramId { get; set; }
        public required string Plan { get; set; }
    }
}
