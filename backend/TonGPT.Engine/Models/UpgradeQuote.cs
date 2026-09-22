using System.ComponentModel.DataAnnotations;

namespace TonGPT.Engine.Models;

public class UpgradeQuote
{
    [Key, MaxLength(32)] public required string Reference { get; set; }
    public required string TelegramId { get; set; }
    public SubscriptionPlan FromPlan { get; set; }
    public SubscriptionPlan TargetPlan { get; set; }
    public DateTime SubscriptionExpiry { get; set; }
    public long EntitlementVersion { get; set; }
    public required string Provider { get; set; }
    public long ExpectedUnits { get; set; } // nanoton or whole Stars
    public DateTime CreatedAt { get; set; }
    public DateTime ValidUntil { get; set; }
    public Guid? AppliedPaymentId { get; set; }
    public string Kind { get; set; } = "upgrade";
    public SubscriptionPlan? PendingPlan { get; set; }
    public DateTime? PendingStartsAt { get; set; }
    public DateTime? PendingExpiry { get; set; }
}

// An immutable receipt for a payment whose entitlement application was rejected.
// General historical Stars-ledger backfill remains a separate step.
public class PaymentReconciliation
{
    [Key] public Guid PaymentId { get; set; }
    public string? QuoteReference { get; set; }
    public required string Reason { get; set; }
    public required string Currency { get; set; }
    public decimal ActualUnits { get; set; }
    public long? ExpectedUnits { get; set; }
    public DateTime? PaidAt { get; set; }
}
