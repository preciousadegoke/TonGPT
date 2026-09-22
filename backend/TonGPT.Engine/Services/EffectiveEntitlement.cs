using TonGPT.Engine.Models;

namespace TonGPT.Engine.Services;

public record Entitlement(SubscriptionPlan Plan, DateTime? Expiry,
    SubscriptionPlan? PendingPlan = null, DateTime? PendingStartsAt = null, DateTime? PendingExpiry = null);

public static class EffectiveEntitlement
{
    // Pure projection: no mutation, database access, clock reads or scheduled job.
    public static Entitlement Resolve(User? user, DateTime now)
    {
        if (user == null) return new(SubscriptionPlan.Free, null);
        var hasPending = user.PendingPlan != null || user.PendingStartsAt != null || user.PendingExpiry != null;
        if (hasPending)
        {
            if (user.PendingPlan is null or SubscriptionPlan.Free || !Enum.IsDefined(user.PendingPlan.Value)
                || user.PendingStartsAt == null || user.PendingExpiry <= user.PendingStartsAt || user.PendingExpiry == null
                || user.PendingStartsAt != user.SubscriptionExpiry)
                return new(SubscriptionPlan.Free, null); // Inconsistent paid coverage must not grant access.
            if (now >= user.PendingStartsAt)
                return now < user.PendingExpiry ? new(user.PendingPlan.Value, user.PendingExpiry) : new(SubscriptionPlan.Free, null);
        }
        return user.Plan != SubscriptionPlan.Free && Enum.IsDefined(user.Plan) && user.SubscriptionExpiry > now
            ? new(user.Plan, user.SubscriptionExpiry, user.PendingPlan, user.PendingStartsAt, user.PendingExpiry)
            : new(SubscriptionPlan.Free, null);
    }

    public static bool Matches(User? user, UpgradeQuote quote, DateTime now)
    {
        var effective = Resolve(user, now);
        return user != null && effective.Plan == quote.FromPlan && effective.Expiry == quote.SubscriptionExpiry
            && user.EntitlementVersion == quote.EntitlementVersion && user.PendingPlan == quote.PendingPlan
            && user.PendingStartsAt == quote.PendingStartsAt && user.PendingExpiry == quote.PendingExpiry;
    }

    // Only call on a locked user INSIDE the payment transaction, after validating
    // its quote snapshot. Reads and rejected/held receipts never normalize state.
    public static void NormalizeForPayment(User user, DateTime now)
    {
        if (user.PendingStartsAt == null || user.PendingStartsAt > now) return;
        var effective = Resolve(user, now);
        user.Plan = effective.Plan;
        user.SubscriptionExpiry = effective.Expiry;
        user.PendingPlan = null;
        user.PendingStartsAt = null;
        user.PendingExpiry = null;
    }

    public static void Schedule(User user, SubscriptionPlan target, DateTime now)
    {
        var effective = Resolve(user, now);
        if (effective.Plan == SubscriptionPlan.Free || target <= SubscriptionPlan.Free || target >= effective.Plan
            || !Enum.IsDefined(target) || (effective.PendingPlan != null && effective.PendingPlan != target))
            throw new InvalidOperationException("Conflicting pending downgrade");
        NormalizeForPayment(user, now);
        user.PendingPlan = target;
        user.PendingStartsAt = user.SubscriptionExpiry;
        user.PendingExpiry = (user.PendingExpiry ?? user.SubscriptionExpiry)!.Value.AddDays(UpgradePricing.CycleDays);
    }
}
