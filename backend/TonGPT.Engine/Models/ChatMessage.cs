using System;
using System.ComponentModel.DataAnnotations;

namespace TonGPT.Engine.Models
{
    public class ChatMessage
    {
        [Key]
        public long Id { get; set; }

        public required string TelegramId { get; set; }

        public string? UserMessage { get; set; }

        public string? AiResponse { get; set; }

        public DateTime Timestamp { get; set; } = DateTime.UtcNow;
    }
}
