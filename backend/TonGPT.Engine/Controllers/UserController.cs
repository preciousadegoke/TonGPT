using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using TonGPT.Engine.Data;
using TonGPT.Engine.Models;
using System.Threading.Tasks;

namespace TonGPT.Engine.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class UserController : ControllerBase
    {
        private readonly AppDbContext _context;

        public UserController(AppDbContext context)
        {
            _context = context;
        }

        public class UserSyncDto
        {
            public long TelegramId { get; set; }
            public string? Username { get; set; }
            public string? FirstName { get; set; }
            public string? LastName { get; set; }
        }

        [HttpPost("sync")]
        public async Task<IActionResult> SyncUser([FromBody] UserSyncDto userDto)
        {
            var telegramIdStr = userDto.TelegramId.ToString();

            var user = await _context.Users.FirstOrDefaultAsync(u => u.TelegramId == telegramIdStr);

            if (user == null)
            {
                user = new User
                {
                    TelegramId = telegramIdStr,
                    Username = userDto.Username,
                    FirstName = userDto.FirstName,
                    LastName = userDto.LastName,
                    CreatedAt = DateTime.UtcNow,
                    Plan = SubscriptionPlan.Free
                };
                _context.Users.Add(user);
            }
            else
            {
                // Update existing info
                user.Username = userDto.Username;
                user.FirstName = userDto.FirstName;
                user.LastName = userDto.LastName;
            }

            await _context.SaveChangesAsync();
            return Ok(new { status = "Success", userId = user.Id });
        }

        [HttpGet("{telegramId}")]
        public async Task<IActionResult> GetUser(string telegramId)
        {
            var user = await _context.Users.FirstOrDefaultAsync(u => u.TelegramId == telegramId);

            if (user == null)
            {
                return NotFound(new { message = "User not found" });
            }

            return Ok(new
            {
                telegramId = user.TelegramId,
                username = user.Username,
                plan = user.Plan.ToString(),
                expiry = user.SubscriptionExpiry
            });
        }
    }
}
