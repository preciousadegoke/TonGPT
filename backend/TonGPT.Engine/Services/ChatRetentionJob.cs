using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using TonGPT.Engine.Data;

namespace TonGPT.Engine.Services
{
    public class ChatRetentionJob : BackgroundService
    {
        private readonly IServiceScopeFactory _scopeFactory;
        private readonly ILogger<ChatRetentionJob> _logger;
        private const int RetentionDays = 90;

        public ChatRetentionJob(IServiceScopeFactory scopeFactory, ILogger<ChatRetentionJob> logger)
        {
            _scopeFactory = scopeFactory;
            _logger = logger;
        }

        protected override async Task ExecuteAsync(CancellationToken stoppingToken)
        {
            while (!stoppingToken.IsCancellationRequested)
            {
                try
                {
                    using var scope = _scopeFactory.CreateScope();
                    var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
                    var cutoff = DateTime.UtcNow.AddDays(-RetentionDays);
                    var deleted = await db.ChatMessages
                        .Where(m => m.Timestamp < cutoff)
                        .ExecuteDeleteAsync(stoppingToken);

                    if (deleted > 0)
                        _logger.LogInformation(
                            "Retention: deleted {Count} messages older than {Days}d",
                            deleted, RetentionDays
                        );
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Chat retention job failed");
                }

                await Task.Delay(TimeSpan.FromHours(24), stoppingToken);
            }
        }
    }
}

