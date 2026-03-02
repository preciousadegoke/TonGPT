using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using TonGPT.Engine.Data;
using TonGPT.Engine.Models;
using System.Threading.Tasks;

namespace TonGPT.Engine.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class WalletController : ControllerBase
    {
        private readonly AppDbContext _context;
        private readonly ILogger<WalletController> _logger;

        public WalletController(AppDbContext context, ILogger<WalletController> logger)
        {
            _context = context;
            _logger = logger;
        }

        public class WalletAuthDto
        {
            public long TelegramId { get; set; }
            public required string Address { get; set; }
            public required string PublicKey { get; set; }
            public required string Proof { get; set; } // TON Connect "ton_proof" payload
            public string? StateInit { get; set; }
        }

        [HttpPost("auth")]
        public async Task<IActionResult> AuthenticateWallet([FromBody] WalletAuthDto authDto)
        {
            var redactedAddress = authDto.Address.Length > 10 ? $"{authDto.Address.Substring(0, 6)}...{authDto.Address.Substring(authDto.Address.Length - 4)}" : "***";
            _logger.LogInformation($"Authenticating wallet {redactedAddress} for user {authDto.TelegramId}");

            // Only accept proofs that have been verified by the Python server.
            // Direct client calls with raw ton_proof payloads are rejected.
            if (authDto.Proof != "VERIFIED_BY_PYTHON_SERVER")
            {
                _logger.LogWarning($"Rejected unverified proof from user {authDto.TelegramId}");
                return StatusCode(403, new { message = "Wallet proof must be verified by the API server first." });
            }

            var user = await _context.Users.FirstOrDefaultAsync(u => u.TelegramId == authDto.TelegramId.ToString());

            if (user == null)
            {
                return NotFound(new { message = "User not found. Please start the bot first." });
            }

            // Check if this wallet is already linked to a different user
            var existingOwner = await _context.Users.FirstOrDefaultAsync(u =>
                u.WalletAddress == authDto.Address && u.TelegramId != authDto.TelegramId.ToString());
            if (existingOwner != null)
            {
                _logger.LogWarning($"Wallet {redactedAddress} already linked to user {existingOwner.TelegramId}");
                return Conflict(new { message = "This wallet is already linked to another account." });
            }

            // Update user with wallet address
            user.WalletAddress = authDto.Address;
            _context.ActivityLogs.Add(new ActivityLog
            {
                TelegramId = authDto.TelegramId.ToString(),
                Action = "wallet_linked",
                Metadata = System.Text.Json.JsonSerializer.Serialize(new { Address = redactedAddress }),
                Success = true,
                Timestamp = DateTime.UtcNow
            });
            await _context.SaveChangesAsync();

            return Ok(new
            {
                status = "Success",
                message = "Wallet linked successfully",
                wallet = user.WalletAddress
            });
        }

        [HttpGet("status/{telegramId}")]
        public async Task<IActionResult> GetWalletStatus(string telegramId)
        {
            var user = await _context.Users.FirstOrDefaultAsync(u => u.TelegramId == telegramId);

            if (user == null) return NotFound("User not found");

            return Ok(new
            {
                telegramId = user.TelegramId,
                walletAddress = user.WalletAddress,
                isLinked = !string.IsNullOrEmpty(user.WalletAddress)
            });
        }
    }
}
