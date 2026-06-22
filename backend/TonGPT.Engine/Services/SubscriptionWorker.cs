using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Configuration;
using Microsoft.EntityFrameworkCore;
using TonGPT.Engine.Data;
using System;
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
            // It also predates the canonical tier values, so leave it OFF unless
            // you have deployed and re-audited the matching contract.
            // Enable explicitly with Subscription:EnablePolling = true.
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
            // FIX-1: Read from renamed config key (was SubscriptionContractAddress)
            var contractAddress = _config["TonCenter:ContractAddress"];
            if (string.IsNullOrWhiteSpace(contractAddress) || contractAddress.StartsWith("EQD..."))
            {
                _logger.LogCritical(
                    "SubscriptionContractAddress is not configured or is a placeholder. " +
                    "Subscription polling disabled. Set TonCenter:ContractAddress in appsettings.json.");
                return;
            }

            // FIX-1: Read base URL from renamed config key (was TonCenter:Url)
            var tonApiBaseUrl = _config["TonCenter:BaseUrl"];
            if (string.IsNullOrWhiteSpace(tonApiBaseUrl))
            {
                _logger.LogCritical(
                    "TonCenter:BaseUrl is not configured. Subscription polling disabled. " +
                    "Set TonCenter:BaseUrl in appsettings.json.");
                return;
            }
            // Construct the full runGetMethod endpoint from base URL
            var tonApiUrl = $"{tonApiBaseUrl.TrimEnd('/')}/runGetMethod";

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
                            await CheckUserSubscription(user, context, contractAddress, tonApiUrl);
                        }
                        
                        await context.SaveChangesAsync(stoppingToken); // Bulk save after updates
                    }
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
            User user, AppDbContext context,
            string contractAddress, string tonApiUrl)
        {
             if (string.IsNullOrEmpty(user.WalletAddress)) return;

             try 
             {
                 var client = _httpClientFactory.CreateClient();
                 var payload = new 
                 {
                     address = contractAddress,
                     method = "getSubscription",
                     stack = new object[] { new object[] { "tvm.Slice", user.WalletAddress } }
                 };

                 var response = await client.PostAsJsonAsync(tonApiUrl, payload);
                 
                 if (response.IsSuccessStatusCode)
                 {
                     var json = await response.Content.ReadFromJsonAsync<JsonElement>();
                     
                     // Check for successful execution (exit_code 0 or similar)
                     if (json.TryGetProperty("ok", out var ok) && ok.GetBoolean() && 
                         json.TryGetProperty("result", out var result))
                     {
                         if (result.TryGetProperty("exit_code", out var exitCode) && exitCode.GetInt32() == 0)
                         {
                             // Parse stack: [tier, expiry]
                             var stack = result.GetProperty("stack");
                             if (stack.GetArrayLength() >= 2)
                             {
                                 // Stack items are like: ["num", "0x..."]
                                 var tierHex = stack[0].GetProperty("value").GetString(); // "0x1"
                                 var expiryHex = stack[1].GetProperty("value").GetString(); // "0x..."
                                 
                                 long tier = Convert.ToInt64(tierHex, 16);
                                 long expiryTimestamp = Convert.ToInt64(expiryHex, 16);
                                 
                                 // FIX-1: Tier values updated to match confirmed pricing
                                 // constants.tact: TIER_STARTER=10e9, TIER_PRO=30e9,
                                 //   TIER_PRO_PLUS=60e9, TIER_ELITE=120e9
                                 var newPlan = tier switch
                                 {
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
                             }
                         }
                     }
                 }
             }
             catch (Exception ex)
             {
                 _logger.LogWarning($"Failed to check subscription for {user.WalletAddress}: {ex.Message}");
             }
        }
    }
}
