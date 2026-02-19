using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using TonGPT.Engine.Data;
using TonGPT.Engine.Models;
using System.Threading.Tasks;

namespace TonGPT.Engine.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class AnalyticsController : ControllerBase
    {
        private readonly AppDbContext _context;

        public AnalyticsController(AppDbContext context)
        {
            _context = context;
        }

        public class ActivityLogDto
        {
            public long TelegramId { get; set; }
            public required string Action { get; set; }
            public string? Metadata { get; set; }
            public bool Success { get; set; } = true;
        }

        [HttpPost("log")]
        public async Task<IActionResult> LogActivity([FromBody] ActivityLogDto logDto)
        {
            var log = new ActivityLog
            {
                TelegramId = logDto.TelegramId.ToString(),
                Action = logDto.Action,
                Metadata = logDto.Metadata,
                Success = logDto.Success,
                Timestamp = DateTime.UtcNow
            };

            _context.ActivityLogs.Add(log);
            await _context.SaveChangesAsync();

            return Ok(new { status = "Success" });
        }

        [HttpGet("dashboard")]
        public async Task<IActionResult> GetDashboardStats()
        {
            try
            {
                var totalUsers = await _context.Users.CountAsync();
                var linkedWallets = await _context.Users.CountAsync(u => !string.IsNullOrEmpty(u.WalletAddress));
                
                var planStats = await _context.Users
                    .GroupBy(u => u.Plan)
                    .Select(g => new { Plan = g.Key.ToString(), Count = g.Count() })
                    .ToDictionaryAsync(x => x.Plan, x => x.Count);

                var recentActivity = await _context.ActivityLogs
                    .OrderByDescending(l => l.Timestamp)
                    .Take(10)
                    .Select(l => new { l.Action, l.Timestamp, l.Success })
                    .ToListAsync();

                return Ok(new
                {
                    TotalUsers = totalUsers,
                    LinkedWallets = linkedWallets,
                    PlanDistribution = planStats,
                    RecentActivity = recentActivity
                });
            }
            catch (Exception ex)
            {
                return StatusCode(500, new { message = "Failed to load analytics", error = ex.Message });
            }
        }
    }
}
