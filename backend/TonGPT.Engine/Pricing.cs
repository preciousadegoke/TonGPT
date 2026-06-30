using System.Collections.Generic;
using TonGPT.Engine.Models;

namespace TonGPT.Engine
{
    /// <summary>
    /// Canonical subscription pricing for server-side amount validation (PAY-001).
    ///
    /// SINGLE SOURCE OF TRUTH IS <c>core/pricing.py</c> (Python). This table MUST
    /// mirror it exactly. If you change a price there, change it here too — the two
    /// are intentionally kept in lock-step so the Engine can reject underpayment
    /// independently of any caller.
    ///
    ///   Tier      TON    Stars
    ///   Starter    10     1335
    ///   Pro        30     4000
    ///   Pro+       60     8000
    ///   Elite     120    16000
    /// </summary>
    public static class Pricing
    {
        public readonly record struct PlanPrice(decimal Ton, long Stars);

        private static readonly Dictionary<SubscriptionPlan, PlanPrice> _prices = new()
        {
            [SubscriptionPlan.Starter] = new PlanPrice(10m, 1335),
            [SubscriptionPlan.Pro]     = new PlanPrice(30m, 4000),
            [SubscriptionPlan.ProPlus] = new PlanPrice(60m, 8000),
            [SubscriptionPlan.Elite]   = new PlanPrice(120m, 16000),
        };

        /// <summary>Accept payments up to this fraction under the TON price, matching
        /// the on-chain monitor's tolerance so the Engine never rejects a transfer the
        /// monitor already accepted. Stars are charged exactly, so they have no tolerance.</summary>
        public const decimal TonTolerance = 0.02m; // 2%

        public static bool TryGet(SubscriptionPlan plan, out PlanPrice price)
            => _prices.TryGetValue(plan, out price);
    }
}
