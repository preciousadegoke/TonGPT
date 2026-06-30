"""
core/pricing.py — SINGLE SOURCE OF TRUTH for TonGPT subscription pricing.

WHY THIS FILE EXISTS
--------------------
Pricing previously lived in three places that disagreed with each other:
  * handlers/pay.py        -> Starter/Pro/Pro+/Elite at 10/30/60/120 TON
  * the Tolk contract      -> BASIC/PRO/ENTERPRISE at 0.5/1/2 TON  (outlier)
  * the C# SubscriptionWorker -> nanoton tiers 10e9/30e9/60e9/120e9

This module is now the ONE place pricing is defined. Everything else imports
from here so the numbers can never drift again.

CANONICAL PRICING MODEL (chosen)
--------------------------------
We keep the marketing tiers and anchor every payment channel to the SAME USD
value so there is no arbitrage between paying with Telegram Stars vs TON:

    Tier      USD       TON     Stars     Queries/day
    Starter   $22.70    10      1335      100
    Pro       $68.10    30      4000      500
    Pro+      $136.20   60      8000      1000
    Elite     $272.40   120     16000     unlimited

Reference rate: 1 TON ≈ $2.27, 1 Star ≈ $0.017.

NOTE FOR THE OPERATOR: these TON amounts are on the higher side. They are kept
here (a) to match the existing Stars pricing exactly and (b) because the C#
worker + Tact constants already use them. To change pricing, edit ONLY this
file — every channel will follow. If you lower TON prices, lower Stars too, or
users will simply pay via the cheaper channel.

TON amounts are fixed-per-tier (not dynamically re-quoted) so the user always
knows the exact amount to send and on-chain validation is unambiguous.

TELEGRAM STARS (XTR) AMOUNT RULE — READ BEFORE TOUCHING ANY INVOICE CODE
-----------------------------------------------------------------------
Telegram Stars use the currency code "XTR". For XTR, the LabeledPrice ``amount``
is the WHOLE NUMBER OF STARS — it is NOT multiplied by 100.

    ✅ correct:   LabeledPrice(label=..., amount=plan["price_stars"])   # 1335 Stars
    ❌ wrong:     LabeledPrice(label=..., amount=plan["price_stars"]*100)  # 133,500 Stars (100×)

The ×100 ("smallest subunit") convention applies ONLY to fiat currencies like
USD, where amount=100 means $1.00. XTR has no subunit. Likewise the amount
returned in ``successful_payment.total_amount`` for an XTR payment is the whole
Star count, so it must be compared directly to ``price_stars`` (no ``// 100``).
Use ``expected_stars(plan_key)`` below as the single source for that value.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# Ordered list of canonical plan keys (cheapest -> most expensive).
PLAN_ORDER: List[str] = ["starter", "pro", "pro_plus", "elite"]

# USD anchor per tier (used for Stars/TON validation tolerance math).
PLAN_PRICES_USD: Dict[str, float] = {
    "starter": 22.70,
    "pro": 68.10,
    "pro_plus": 136.20,
    "elite": 272.40,
}

# Full plan definitions. price_nanoton = price_ton * 1e9 (kept explicit to avoid
# float rounding surprises on-chain).
PLANS: Dict[str, dict] = {
    "starter": {
        "name": "Starter Plan",
        "price_ton": 10,
        "price_nanoton": 10_000_000_000,
        "price_stars": 1335,
        "duration_days": 30,
        "features": [
            "100 AI queries per day",
            "Basic market alerts",
            "Standard response speed",
            "Email support",
        ],
        "queries_per_day": 100,
        "whale_threshold": 100,
    },
    "pro": {
        "name": "Pro Plan",
        "price_ton": 30,
        "price_nanoton": 30_000_000_000,
        "price_stars": 4000,
        "duration_days": 30,
        "features": [
            "500 AI queries per day",
            "Advanced whale alerts",
            "Priority support",
            "Custom notifications",
            "Portfolio tracking",
        ],
        "queries_per_day": 500,
        "whale_threshold": 50,
    },
    "pro_plus": {
        "name": "Pro+ Plan",
        "price_ton": 60,
        "price_nanoton": 60_000_000_000,
        "price_stars": 8000,
        "duration_days": 30,
        "features": [
            "1000 AI queries per day",
            "Real-time market data",
            "Advanced analytics",
            "API access (100 calls/day)",
            "Advanced charts",
        ],
        "queries_per_day": 1000,
        "whale_threshold": 25,
    },
    "elite": {
        "name": "Elite Plan",
        "price_ton": 120,
        "price_nanoton": 120_000_000_000,
        "price_stars": 16000,
        "duration_days": 30,
        "features": [
            "Unlimited AI queries",
            "VIP whale alerts",
            "Custom API access",
            "Direct developer support",
            "1-on-1 support calls",
        ],
        "queries_per_day": -1,
        "whale_threshold": 10,
    },
}

# Map Python plan key -> C# SubscriptionPlan enum name (Engine activation).
_PLAN_TO_ENGINE = {
    "starter": "Starter",
    "pro": "Pro",
    "pro_plus": "ProPlus",
    "elite": "Elite",
}


def plan_to_engine(plan_key: str) -> str:
    """Translate a Python plan key to the C# SubscriptionPlan enum name."""
    return _PLAN_TO_ENGINE.get(plan_key, plan_key)


def is_valid_plan(plan_key: str) -> bool:
    return plan_key in PLANS


def expected_nanoton(plan_key: str) -> Optional[int]:
    """Exact nanoton amount required for a tier, or None if unknown."""
    plan = PLANS.get(plan_key)
    return int(plan["price_nanoton"]) if plan else None


def expected_stars(plan_key: str) -> Optional[int]:
    """Exact Telegram Stars (XTR) amount required for a tier, or None if unknown.

    This is the value to pass DIRECTLY as the LabeledPrice ``amount`` for an XTR
    invoice — do NOT multiply by 100 (see the XTR amount rule in the module
    docstring). It is also the value ``successful_payment.total_amount`` must be
    compared against for an XTR payment.
    """
    plan = PLANS.get(plan_key)
    return int(plan["price_stars"]) if plan else None


def duration_days(plan_key: str) -> int:
    plan = PLANS.get(plan_key)
    return int(plan["duration_days"]) if plan else 30


__all__ = [
    "PLAN_ORDER",
    "PLAN_PRICES_USD",
    "PLANS",
    "plan_to_engine",
    "is_valid_plan",
    "expected_nanoton",
    "expected_stars",
    "duration_days",
]
