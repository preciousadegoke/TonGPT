using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace TonGPT.Engine.Models
{
    public class Payment
    {
        [Key]
        public Guid Id { get; set; }

        public required string TelegramUserId { get; set; }

        [Column(TypeName = "decimal(18, 9)")]
        public decimal AmountTon { get; set; }

        public string? TransactionHash { get; set; }

        public string Status { get; set; } = "Pending"; // Pending, Completed, Failed

        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

        /// <summary>Subscription plan this payment is for (e.g. starter, pro).</summary>
        public string? Plan { get; set; }

        /// <summary>Payment provider (e.g. telegram_stars, ton_manual).</summary>
        public string? Provider { get; set; }

        /// <summary>External id from provider (e.g. Telegram payment charge id).</summary>
        public string? ExternalId { get; set; }
    }
}
