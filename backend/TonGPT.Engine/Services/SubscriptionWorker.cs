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

            // C-16: Startup guard — refuse to poll a placeholder or missing contract address
            var contractAddress = _config["TonCenter:SubscriptionContractAddress"];
            if (string.IsNullOrWhiteSpace(contractAddress) || contractAddress.StartsWith("EQD..."))
            {
                _logger.LogCritical(
                    "SubscriptionContractAddress is not configured or is a placeholder. " +
                    "Subscription polling disabled. Set TonCenter:SubscriptionContractAddress in appsettings.json.");
                return;
            }

            // C-15: Read TON API URL from configuration instead of hardcoding testnet
            var tonApiUrl = _config["TonCenter:Url"];
            if (string.IsNullOrWhiteSpace(tonApiUrl))
            {
                _logger.LogCritical(
                    "TonCenter:Url is not configured. Subscription polling disabled. " +
                    "Set TonCenter:Url in appsettings.json.");
                return;
            }

            _logger.LogInformation(
                "Subscription Worker configured: Contract={ContractAddress}, API={ApiUrl}",
                contractAddress, tonApiUrl);

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
                                 
                                 int tier = Convert.ToInt32(tierHex, 16);
                                 long expiryTimestamp = Convert.ToInt64(expiryHex, 16);
                                 
                                 // Map to Plan
                                 var newPlan = tier switch
                                 {
                                     1 => SubscriptionPlan.Starter,
                                     2 => SubscriptionPlan.Pro,
                                     3 => SubscriptionPlan.Elite,
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
