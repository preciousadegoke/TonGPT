using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Configuration;
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
        private readonly int _retentionDays;
        private readonly int _activityRetentionDays;

        public ChatRetentionJob(
            IServiceScopeFactory scopeFactory,
            ILogger<ChatRetentionJob> logger,
            IConfiguration config)
        {
            _scopeFactory = scopeFactory;
            _logger = logger;
            _retentionDays = config.GetValue<int>("RetentionDays", 30);
            // DATA-001: bound ActivityLogs growth. Longer default so the audit
            // trail is preserved but the table can never grow without limit.
            _activityRetentionDays = config.GetValue<int>("ActivityRetentionDays", 365);
        }

        protected override async Task ExecuteAsync(CancellationToken stoppingToken)
        {
            while (!stoppingToken.IsCancellationRequested)
            {
                try
                {
                    using var scope = _scopeFactory.CreateScope();
                    var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
                    var cutoff = DateTime.UtcNow.AddDays(-_retentionDays);
                    var deleted = await db.ChatMessages
                        .Where(m => m.Timestamp < cutoff)
                        .ExecuteDeleteAsync(stoppingToken);

                    if (deleted > 0)
                        _logger.LogInformation(
                            "Retention: deleted {Count} messages older than {Days}d",
                            deleted, _retentionDays
                        );

                    // DATA-001: prune old ActivityLogs so the table stays bounded.
                    var activityCutoff = DateTime.UtcNow.AddDays(-_activityRetentionDays);
                    var logsDeleted = await db.ActivityLogs
                        .Where(a => a.Timestamp < activityCutoff)
                        .ExecuteDeleteAsync(stoppingToken);

                    if (logsDeleted > 0)
                        _logger.LogInformation(
                            "Retention: deleted {Count} activity logs older than {Days}d",
                            logsDeleted, _activityRetentionDays
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

