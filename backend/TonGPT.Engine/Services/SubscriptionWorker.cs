using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Configuration;
using Microsoft.EntityFrameworkCore;
using TonGPT.Engine.Data;
using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Net.Http;
using System.Text.Json;
using System.Net.Http.Json; // Required for PostAsJsonAsync
using TonGPT.Engine.Models; // Ensure Models namespace is imported

namespace TonGPT.Engine.Services
{
    public class SubscriptionWorker : BackgroundService
    {
        private readonly IServiceProvider _serviceProvider;
        private readonly ILogger<SubscriptionWorker> _logger;
        private readonly IHttpClientFactory _httpClientFactory;
        private readonly IConfiguration _config;

        public SubscriptionWorker(
            IServiceProvider serviceProvider,
            ILogger<SubscriptionWorker> logger,
            IHttpClientFactory httpClientFactory,
            IConfiguration config)
        {
            _serviceProvider = serviceProvider;
            _logger = logger;
            _httpClientFactory = httpClientFactory;
            _config = config;
        }

        protected override async Task ExecuteAsync(CancellationToken stoppingToken)
        {
            _logger.LogInformation("Subscription Worker is starting.");

            // ============================================================
            // GATED OFF BY DEFAULT.
            // The canonical, live TON payment path is OFF-CHAIN: the Python
            // bot monitors a single wallet for memo-tagged transfers and
            // activates via Payment/complete (see services/ton_payments.py).
            // This on-chain get-method poller is an OPTIONAL alternative for a
            // future fully-on-chain subscription contract and is NOT used today.
            // Enable explicitly with Subscription:EnablePolling = true.
            //
            // LAUNCH-FIX NOTE (2026-07-03): a stale Docker image built from
            // pre-gate source ran this worker despite the flag being unset,
            // producing the toncenter 422 loop + thread-pool pressure seen in
            // the boot log. If you see "Checking subscriptions..." without
            // setting Subscription:EnablePolling=true, REBUILD the image:
            //     docker compose build --no-cache tongpt-engine
            // ============================================================
            var pollingEnabled = string.Equals(
                _config["Subscription:EnablePolling"], "true", StringComparison.OrdinalIgnoreCase);
            if (!pollingEnabled)
            {
                _logger.LogInformation(
                    "SubscriptionWorker disabled (Subscription:EnablePolling != true). " +
                    "Canonical TON activation is handled off-chain via Payment/complete.");
                return;
            }

            // C-16: Startup guard — refuse to poll a placeholder or missing contract address
            var contractAddress = _config["TonCenter:ContractAddress"];
            if (string.IsNullOrWhiteSpace(contractAddress) || contractAddress.StartsWith("EQD..."))
            {
                _logger.LogCritical(
                    "SubscriptionContractAddress is not configured or is a placeholder. " +
                    "Subscription polling disabled. Set TonCenter:ContractAddress in appsettings.json.");
                return;
            }

            var tonApiBaseUrl = _config["TonCenter:BaseUrl"];
            if (string.IsNullOrWhiteSpace(tonApiBaseUrl))
            {
                _logger.LogCritical(
                    "TonCenter:BaseUrl is not configured. Subscription polling disabled. " +
                    "Set TonCenter:BaseUrl in appsettings.json.");
                return;
            }
            var tonApiUrl = $"{tonApiBaseUrl.TrimEnd('/')}/runGetMethod";

            // LAUNCH-FIX 1: toncenter throttles keyless clients aggressively
            // (the 6–12s latencies in the boot log). Wire the API key.
            var apiKey = _config["TonCenter:ApiKey"]
                         ?? Environment.GetEnvironmentVariable("TONCENTER_API_KEY")
                         ?? Environment.GetEnvironmentVariable("TONCENTER_API");
            if (string.IsNullOrWhiteSpace(apiKey))
            {
                _logger.LogWarning(
                    "No toncenter API key configured (TonCenter:ApiKey / TONCENTER_API_KEY). " +
                    "Requests will be heavily rate-limited.");
            }

            _logger.LogInformation(
                "Subscription Worker configured: Contract={ContractAddress}, API={ApiUrl}, Network={Network}",
                contractAddress, tonApiUrl, _config["TonCenter:Network"] ?? "unknown");

            while (!stoppingToken.IsCancellationRequested)
            {
                _logger.LogInformation("Checking subscriptions...");

                try
                {
                    using (var scope = _serviceProvider.CreateScope())
                    {
                        var context = scope.ServiceProvider.GetRequiredService<AppDbContext>();
                        var usersWithWallets = await context.Users
                            .Where(u => !string.IsNullOrEmpty(u.WalletAddress))
                            .ToListAsync(stoppingToken);

                        foreach (var user in usersWithWallets)
                        {
                            await CheckUserSubscription(user, contractAddress, tonApiUrl, apiKey, stoppingToken);
                        }

                        await context.SaveChangesAsync(stoppingToken); // Bulk save after updates
                    }
                }
                catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
                {
                    break; // clean shutdown
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Error checking subscriptions");
                }

                // Poll every 1 minute
                await Task.Delay(TimeSpan.FromMinutes(1), stoppingToken);
            }
        }

        private async Task CheckUserSubscription(
            User user, string contractAddress, string tonApiUrl,
            string? apiKey, CancellationToken ct)
        {
            if (string.IsNullOrEmpty(user.WalletAddress)) return;

            try
            {
                // LAUNCH-FIX 1 (root cause of the 422s): toncenter v2 expects a
                // slice argument as a BASE64-SERIALIZED BOC, not a raw address
                // string; and the contract's real getter is `subscriptionInfo`
                // (subscription.tolk), not `getSubscription` (ENG-006).
                if (!TryParseTonAddress(user.WalletAddress, out var wc, out var hash))
                {
                    _logger.LogWarning("Unparseable wallet address for user; skipping cycle.");
                    return;
                }
                var sliceBocB64 = Convert.ToBase64String(BuildAddressSliceBoc(wc, hash));

                var payload = new
                {
                    address = contractAddress,
                    method = "subscriptionInfo",
                    stack = new object[] { new object[] { "tvm.Slice", sliceBocB64 } }
                };

                // LAUNCH-FIX 1: named client with an 8s timeout (configured in
                // Program.cs). Fully async + cancellation-aware — a slow
                // toncenter can no longer pile up 100s-default-timeout calls
                // and pressure the pool (the Kestrel heartbeat warning).
                var client = _httpClientFactory.CreateClient("toncenter");
                using var request = new HttpRequestMessage(HttpMethod.Post, tonApiUrl)
                {
                    Content = JsonContent.Create(payload)
                };
                if (!string.IsNullOrWhiteSpace(apiKey))
                {
                    request.Headers.TryAddWithoutValidation("X-API-Key", apiKey);
                }

                using var response = await client.SendAsync(request, ct);

                if (!response.IsSuccessStatusCode)
                {
                    // LAUNCH-FIX 1: log-and-skip instead of silent fall-through,
                    // with enough detail (status + body head) to diagnose.
                    var body = await response.Content.ReadAsStringAsync(ct);
                    _logger.LogWarning(
                        "toncenter runGetMethod returned {Status} for a wallet; skipping this cycle. Body: {Body}",
                        (int)response.StatusCode, body.Length > 300 ? body[..300] : body);
                    return;
                }

                var json = await response.Content.ReadFromJsonAsync<JsonElement>(cancellationToken: ct);

                if (json.TryGetProperty("ok", out var ok) && ok.GetBoolean() &&
                    json.TryGetProperty("result", out var result))
                {
                    if (result.TryGetProperty("exit_code", out var exitCode) && exitCode.GetInt32() == 0)
                    {
                        // Parse stack: [tier, expiry]
                        var stack = result.GetProperty("stack");
                        if (stack.GetArrayLength() >= 2 &&
                            TryReadStackNum(stack[0], out long tier) &&
                            TryReadStackNum(stack[1], out long expiryTimestamp))
                        {
                            // ENG-006: the contract stores small uint8 tier codes.
                            // Map those first; keep the legacy nanoton values as a
                            // fallback for older contract builds.
                            var newPlan = tier switch
                            {
                                1L => SubscriptionPlan.Starter,
                                2L => SubscriptionPlan.Pro,
                                3L => SubscriptionPlan.ProPlus,
                                4L => SubscriptionPlan.Elite,
                                10_000_000_000L => SubscriptionPlan.Starter,
                                30_000_000_000L => SubscriptionPlan.Pro,
                                60_000_000_000L => SubscriptionPlan.ProPlus,
                                120_000_000_000L => SubscriptionPlan.Elite,
                                _ => SubscriptionPlan.Free
                            };

                            if (newPlan != SubscriptionPlan.Free)
                            {
                                user.Plan = newPlan;
                                user.SubscriptionExpiry = DateTimeOffset.FromUnixTimeSeconds(expiryTimestamp).UtcDateTime;
                                _logger.LogInformation("Updated subscription for a user to plan {Plan}", newPlan);
                            }
                            else if (tier != 0)
                            {
                                _logger.LogWarning("Unknown on-chain tier value {Tier}; leaving user plan unchanged.", tier);
                            }
                        }
                    }
                    else
                    {
                        _logger.LogDebug("subscriptionInfo returned non-zero exit code for a wallet; skipping.");
                    }
                }
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                throw; // let shutdown propagate
            }
            catch (Exception ex)
            {
                _logger.LogWarning("Failed to check subscription for a wallet: {Message}", ex.Message);
            }
        }

        // ------------------------------------------------------------------ //
        // toncenter v2 stack helpers.
        // Entries come as pair-arrays: ["num", "0x1"] — but be tolerant of the
        // object form {"type":"num","value":"0x1"} some proxies return.
        // ------------------------------------------------------------------ //
        private static bool TryReadStackNum(JsonElement entry, out long value)
        {
            value = 0;
            string? raw = null;
            if (entry.ValueKind == JsonValueKind.Array && entry.GetArrayLength() >= 2)
            {
                raw = entry[1].ValueKind == JsonValueKind.String ? entry[1].GetString() : entry[1].GetRawText();
            }
            else if (entry.ValueKind == JsonValueKind.Object && entry.TryGetProperty("value", out var v))
            {
                raw = v.ValueKind == JsonValueKind.String ? v.GetString() : v.GetRawText();
            }
            if (string.IsNullOrWhiteSpace(raw)) return false;
            raw = raw.Trim().Trim('"');
            try
            {
                value = raw.StartsWith("0x", StringComparison.OrdinalIgnoreCase)
                    ? Convert.ToInt64(raw, 16)
                    : long.Parse(raw);
                return true;
            }
            catch
            {
                return false;
            }
        }

        // ------------------------------------------------------------------ //
        // Minimal TON address -> single-cell BOC (slice) serializer.
        // addr_std$10 anycast:none wc:int8 hash:bits256 = 267 bits + completion
        // tag, wrapped in a one-cell BOC. This is exactly what toncenter v2
        // expects as the base64 value of a "tvm.Slice" stack entry — sending
        // the raw address string was the 422.
        // ------------------------------------------------------------------ //
        internal static byte[] BuildAddressSliceBoc(sbyte workchain, byte[] hash256)
        {
            if (hash256 is not { Length: 32 })
                throw new ArgumentException("hash must be 32 bytes", nameof(hash256));

            var data = new byte[34]; // 272 bits >= 267 data bits + completion tag
            int bitPos = 0;
            void WriteBit(bool b)
            {
                if (b) data[bitPos / 8] |= (byte)(0x80 >> (bitPos % 8));
                bitPos++;
            }
            void WriteByteBits(byte v)
            {
                for (int i = 7; i >= 0; i--) WriteBit(((v >> i) & 1) == 1);
            }

            WriteBit(true); WriteBit(false);        // addr_std$10
            WriteBit(false);                        // anycast: none
            WriteByteBits(unchecked((byte)workchain)); // workchain int8
            foreach (var b in hash256) WriteByteBits(b);
            WriteBit(true);                         // completion tag (non-byte-aligned data)

            var cell = new byte[2 + data.Length];
            cell[0] = 0x00; // d1: 0 refs, ordinary, level 0
            cell[1] = 0x43; // d2: floor(267/8) + ceil(267/8) = 33 + 34 = 67
            Array.Copy(data, 0, cell, 2, data.Length);

            using var ms = new MemoryStream();
            ms.Write(new byte[] { 0xB5, 0xEE, 0x9C, 0x72 }); // serialized_boc magic
            ms.WriteByte(0x01); // no idx/crc/cache, flags 0, ref-size 1 byte
            ms.WriteByte(0x01); // offset size: 1 byte
            ms.WriteByte(0x01); // cell count: 1
            ms.WriteByte(0x01); // root count: 1
            ms.WriteByte(0x00); // absent: 0
            ms.WriteByte((byte)cell.Length); // tot_cells_size
            ms.WriteByte(0x00); // root index
            ms.Write(cell, 0, cell.Length);
            return ms.ToArray();
        }

        // Accepts friendly base64url (EQ…/UQ…/0Q…, 36 bytes) and raw "0:<hex64>".
        internal static bool TryParseTonAddress(string address, out sbyte workchain, out byte[] hash)
        {
            workchain = 0;
            hash = Array.Empty<byte>();
            address = (address ?? "").Trim();
            if (address.Length == 0) return false;

            if (address.Contains(':'))
            {
                var parts = address.Split(':');
                if (parts.Length != 2 || parts[1].Length != 64) return false;
                if (!sbyte.TryParse(parts[0], out workchain)) return false;
                try { hash = Convert.FromHexString(parts[1]); } catch { return false; }
                return true;
            }

            try
            {
                var b64 = address.Replace('-', '+').Replace('_', '/');
                switch (b64.Length % 4) { case 2: b64 += "=="; break; case 3: b64 += "="; break; }
                var bytes = Convert.FromBase64String(b64);
                if (bytes.Length != 36) return false; // tag(1) wc(1) hash(32) crc(2)
                workchain = unchecked((sbyte)bytes[1]);
                hash = bytes[2..34];
                return true;
            }
            catch
            {
                return false;
            }
        }
    }
}
