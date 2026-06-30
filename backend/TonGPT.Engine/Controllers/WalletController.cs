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
    public class WalletController : ControllerBase
    {
        private readonly AppDbContext _context;
        private readonly ILogger<WalletController> _logger;
        private readonly IConfiguration _config;

        public WalletController(AppDbContext context, ILogger<WalletController> logger, IConfiguration config)
        {
            _context = context;
            _logger = logger;
            _config = config;
        }

        public class WalletAuthDto
        {
            public long TelegramId { get; set; }
            public required string Address { get; set; }
            public required string PublicKey { get; set; }
            // Short-lived HMAC assertion minted by the Python API after it has
            // cryptographically verified the TON Connect ton_proof. Shape:
            //   v1|<telegramId>|<address>|<expUnix>|<nonce>|<hmacHex>
            public required string Proof { get; set; }
            public string? StateInit { get; set; }
        }

        // ENG-001: replaces the old "VERIFIED_BY_PYTHON_SERVER" magic string.
        // Validates that `proof` is a fresh HMAC assertion bound to (telegramId,
        // address), signed with WALLET_LINK_SIGNING_SECRET (shared only with the
        // Python verifier). A holder of ENGINE_API_KEY cannot forge this without
        // also holding the signing secret AND a non-expired, address-bound token.
        private bool ValidateLinkAssertion(string proof, long telegramId, string address, out string reason)
        {
            reason = "";
            var secret = _config["WalletLinkSigningSecret"]
                         ?? Environment.GetEnvironmentVariable("WALLET_LINK_SIGNING_SECRET");
            if (string.IsNullOrEmpty(secret))
            {
                reason = "signing secret not configured";
                return false;
            }
            if (string.IsNullOrEmpty(proof) || proof == "VERIFIED_BY_PYTHON_SERVER")
            {
                reason = "missing or legacy proof";
                return false;
            }

            // v1 | telegramId | address | exp | nonce | hmacHex
            var parts = proof.Split('|');
            if (parts.Length != 6 || parts[0] != "v1")
            {
                reason = "malformed assertion";
                return false;
            }

            var body = string.Join("|", parts[0], parts[1], parts[2], parts[3], parts[4]);
            byte[] expectedSig;
            using (var h = new HMACSHA256(Encoding.UTF8.GetBytes(secret)))
            {
                expectedSig = h.ComputeHash(Encoding.UTF8.GetBytes(body));
            }

            byte[] providedSig;
            try { providedSig = Convert.FromHexString(parts[5]); }
            catch { reason = "bad signature encoding"; return false; }

            if (providedSig.Length != expectedSig.Length
                || !CryptographicOperations.FixedTimeEquals(providedSig, expectedSig))
            {
                reason = "signature mismatch";
                return false;
            }

            if (!long.TryParse(parts[3], out var exp)
                || DateTimeOffset.UtcNow.ToUnixTimeSeconds() > exp)
            {
                reason = "assertion expired";
                return false;
            }

            // Bind the token to THIS request: it must be for this user + address.
            if (parts[1] != telegramId.ToString() || parts[2] != address)
            {
                reason = "assertion does not match request";
                return false;
            }

            return true;
        }

        [HttpPost("auth")]
        public async Task<IActionResult> AuthenticateWallet([FromBody] WalletAuthDto authDto)
        {
            _logger.LogInformation("Authenticating wallet for user [ID_REDACTED]");

            // ENG-001: require a valid, fresh, address-bound HMAC assertion — never
            // a constant. Fails closed if the signing secret is not configured.
            if (!ValidateLinkAssertion(authDto.Proof, authDto.TelegramId, authDto.Address, out var reason))
            {
                _logger.LogWarning("Rejected wallet link for user {TelegramId}: {Reason}", authDto.TelegramId, reason);
                return StatusCode(403, new { message = "Wallet link assertion is invalid or expired." });
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
                _logger.LogWarning("Wallet link attempt rejected: address already linked to another user.");
                return Conflict(new { message = "This wallet is already linked to another account." });
            }

            // Update user with wallet address
            user.WalletAddress = authDto.Address;
            _context.ActivityLogs.Add(new ActivityLog
            {
                TelegramId = authDto.TelegramId.ToString(),
                Action = "wallet_linked",
                Metadata = System.Text.Json.JsonSerializer.Serialize(new { Address = "[REDACTED]" }),
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
