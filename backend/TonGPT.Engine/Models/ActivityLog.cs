using System;
using System.ComponentModel.DataAnnotations;

namespace TonGPT.Engine.Models
{
    public class ActivityLog
    {
        [Key]
        public long Id { get; set; }

        public required string TelegramId { get; set; }

        public required string Action { get; set; }

        public string? Metadata { get; set; }

        public bool Success { get; set; } = true;

        public DateTime Timestamp { get; set; } = DateTime.UtcNow;
    }
}
