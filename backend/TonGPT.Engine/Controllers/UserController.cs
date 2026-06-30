using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using TonGPT.Engine.Data;
using TonGPT.Engine.Models;
using System;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;

namespace TonGPT.Engine.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class UserController : ControllerBase
    {
        private readonly AppDbContext _context;
        private readonly IConfiguration _config;
        private readonly ILogger<UserController> _logger;

        public UserController(AppDbContext context, IConfiguration config, ILogger<UserController> logger)
        {
            _context = context;
            _config = config;
            _logger = logger;
        }

        // SEC-001: validate the per-user assertion for sensitive GDPR actions.
        // Token shape: ua1|<action>|<telegramId>|<exp>|<nonce>|<hmacHex>, signed
        // with WALLET_LINK_SIGNING_SECRET (the SAME secret as wallet linking).
        // If the secret is configured we REQUIRE a valid, action+id-bound token,
        // so a leaked API key alone cannot export/erase arbitrary users. If the
        // secret is not configured we log a warning and allow (so existing
        // deployments are not broken) — set the secret to enable enforcement.
        private bool UserAssertionOk(string action, string telegramId)
        {
            var secret = _config["WalletLinkSigningSecret"]
                         ?? Environment.GetEnvironmentVariable("WALLET_LINK_SIGNING_SECRET");
            if (string.IsNullOrEmpty(secret))
            {
                _logger.LogWarning("WALLET_LINK_SIGNING_SECRET not set — {Action} for {Id} allowed WITHOUT per-user assertion (SEC-001 enforcement disabled).", action, telegramId);
                return true;
            }

            var token = Request.Headers["X-User-Assertion"].ToString();
            if (string.IsNullOrEmpty(token)) { _logger.LogWarning("Missing X-User-Assertion for {Action} {Id}", action, telegramId); return false; }

            var parts = token.Split('|');
            if (parts.Length != 6 || parts[0] != "ua1") return false;
            var body = string.Join("|", parts[0], parts[1], parts[2], parts[3], parts[4]);
            byte[] expected;
            using (var h = new HMACSHA256(Encoding.UTF8.GetBytes(secret)))
                expected = h.ComputeHash(Encoding.UTF8.GetBytes(body));
            byte[] provided;
            try { provided = Convert.FromHexString(parts[5]); } catch { return false; }
            if (provided.Length != expected.Length || !CryptographicOperations.FixedTimeEquals(provided, expected)) return false;
            if (!long.TryParse(parts[3], out var exp) || DateTimeOffset.UtcNow.ToUnixTimeSeconds() > exp) return false;
            // Must be for THIS action and THIS user.
            return parts[1] == action && parts[2] == telegramId;
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
                expiry = user.SubscriptionExpiry,
                consentVersion = user.ConsentVersion
            });
        }

        public class UserConsentDto
        {
            public required string TelegramId { get; set; }
            public required string Version { get; set; }
        }

        [HttpPost("recordConsent")]
        public async Task<IActionResult> RecordConsent([FromBody] UserConsentDto dto)
        {
            var user = await _context.Users.FirstOrDefaultAsync(u => u.TelegramId == dto.TelegramId);
            if (user == null)
            {
                user = new User
                {
                    TelegramId = dto.TelegramId,
                    CreatedAt = DateTime.UtcNow,
                    Plan = SubscriptionPlan.Free,
                    ConsentVersion = dto.Version,
                    ConsentAt = DateTime.UtcNow
                };
                _context.Users.Add(user);
            }
            else
            {
                user.ConsentVersion = dto.Version;
                user.ConsentAt = DateTime.UtcNow;
            }

            await _context.SaveChangesAsync();
            return Ok(new { status = "Success" });
        }

        /// <summary>Export all data we hold for the user (GDPR data portability).</summary>
        [HttpGet("export/{telegramId}")]
        public async Task<IActionResult> ExportData(string telegramId)
        {
            if (!UserAssertionOk("export", telegramId))
                return StatusCode(403, new { message = "Per-user authorization required." });

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
            if (!UserAssertionOk("delete", telegramId))
                return StatusCode(403, new { message = "Per-user authorization required." });

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
