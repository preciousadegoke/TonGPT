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

        /// <summary>Export all data we hold for the user (GDPR data portability).</summary>
        [HttpGet("export/{telegramId}")]
        public async Task<IActionResult> ExportData(string telegramId)
        {
            var user = await _context.Users.FirstOrDefaultAsync(u => u.TelegramId == telegramId);
            if (user == null)
                return NotFound(new { message = "User not found" });

            var chatHistory = await _context.ChatMessages
                .Where(m => m.TelegramId == telegramId)
                .OrderBy(m => m.Timestamp)
                .Select(m => new { m.UserMessage, m.AiResponse, m.Timestamp })
                .ToListAsync();

            var activityLogs = await _context.ActivityLogs
                .Where(a => a.TelegramId == telegramId)
                .OrderBy(a => a.Timestamp)
                .Select(a => new { a.Action, a.Metadata, a.Success, a.Timestamp })
                .ToListAsync();

            return Ok(new
            {
                exportedAt = DateTime.UtcNow,
                user = new
                {
                    telegramId = user.TelegramId,
                    username = user.Username,
                    firstName = user.FirstName,
                    lastName = user.LastName,
                    walletAddress = user.WalletAddress,
                    plan = user.Plan.ToString(),
                    subscriptionExpiry = user.SubscriptionExpiry
                },
                chatHistory,
                activityLogs
            });
        }

        /// <summary>Delete or anonymize user data (GDPR right to erasure).</summary>
        [HttpDelete("data/{telegramId}")]
        public async Task<IActionResult> DeleteUserData(string telegramId)
        {
            var user = await _context.Users.FirstOrDefaultAsync(u => u.TelegramId == telegramId);
            if (user == null)
                return NotFound(new { message = "User not found" });

            var chatMessages = await _context.ChatMessages.Where(m => m.TelegramId == telegramId).ToListAsync();
            _context.ChatMessages.RemoveRange(chatMessages);

            var logs = await _context.ActivityLogs.Where(a => a.TelegramId == telegramId).ToListAsync();
            _context.ActivityLogs.RemoveRange(logs);

            user.Username = null;
            user.FirstName = null;
            user.LastName = null;
            user.WalletAddress = null;
            user.Plan = SubscriptionPlan.Free;
            user.SubscriptionExpiry = null;

            await _context.SaveChangesAsync();
            return Ok(new { status = "Success", message = "Your data has been deleted or anonymized." });
        }
    }
}
