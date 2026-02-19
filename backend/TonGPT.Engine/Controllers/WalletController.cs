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
            _logger.LogInformation($"Authenticating wallet {authDto.Address} for user {authDto.TelegramId}");

            // TODO: Implement actual TON Connect signature verification here.
            // This requires verifying the 'ton_proof' against the public key and standard TON prefix.
            // For Phase 2 Goal (Subscription integration), we trust the client-side proof generation for now
            // but MUST implement this before Mainnet production.

            var user = await _context.Users.FirstOrDefaultAsync(u => u.TelegramId == authDto.TelegramId.ToString());

            if (user == null)
            {
                return NotFound(new { message = "User not found. Please start the bot first." });
            }

            // Update user with wallet address
            user.WalletAddress = authDto.Address;
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
