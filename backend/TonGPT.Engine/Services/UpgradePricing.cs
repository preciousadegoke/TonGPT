using System.Numerics;
using TonGPT.Engine.Models;

namespace TonGPT.Engine.Services;

public static class UpgradePricing
{
    // Canonical billing cadence in core/pricing.py: every paid tier is 30 days.
    public const int CycleDays = 30;
    public static long Units(SubscriptionPlan from, SubscriptionPlan to, string provider, TimeSpan remaining)
    {
        if (to <= from || remaining <= TimeSpan.Zero || !Pricing.TryGet(from, out var oldPrice)
            || !Pricing.TryGet(to, out var newPrice)) throw new ArgumentException("Not an active upgrade");
        long delta = provider switch {
            "ton" => checked((long)((newPrice.Ton - oldPrice.Ton) * 1_000_000_000m)),
            "telegram_stars" => newPrice.Stars - oldPrice.Stars,
            _ => throw new ArgumentException("Unsupported upgrade currency"),
        };
        // remaining_days * (new_cycle_price - old_cycle_price) / 30.
        // Exact integer ceiling, once, in the currency's smallest unit.
        var numerator = (BigInteger)remaining.Ticks * delta;
        var denominator = TimeSpan.FromDays(CycleDays).Ticks;
        return checked((long)((numerator + denominator - 1) / denominator));
    }
}
