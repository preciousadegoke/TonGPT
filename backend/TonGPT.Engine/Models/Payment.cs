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
    }
}
