using System;
using System.ComponentModel.DataAnnotations;

namespace TonGPT.Engine.Models
{
    public enum SubscriptionPlan
    {
        Free,
        Starter,
        Pro,
        Elite
    }

    public class User
    {
        [Key]
        public long Id { get; set; }

        public required string TelegramId { get; set; }

        public string? Username { get; set; }

        public string? FirstName { get; set; }

        public string? LastName { get; set; }

        public string? WalletAddress { get; set; }

        public SubscriptionPlan Plan { get; set; } = SubscriptionPlan.Free;

        public DateTime? SubscriptionExpiry { get; set; }

        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    }
}
