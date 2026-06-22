"""
core/rate_limiting.py — COMPATIBILITY SHIM
==========================================

The real implementation now lives in ``core/rate_limiter.py`` (single source of
truth). This module is kept only so existing imports keep working:

    from core.rate_limiting import get_rate_limiter, create_rate_limit_decorator
    from core.rate_limiting import AdvancedRateLimiter   # legacy alias

Do NOT add new logic here — extend ``core/rate_limiter.py`` instead.
"""

from __future__ import annotations

from core.rate_limiter import (  # noqa: F401  (re-exported on purpose)
    RateLimiter,
    RateLimitDecision,
    TierLimit,
    create_rate_limit_decorator,
    get_rate_limiter,
    init_rate_limiter,
    rate_limit,
    reset_rate_limiter,
)

# Legacy name used by older code/imports.
AdvancedRateLimiter = RateLimiter

__all__ = [
    "RateLimiter",
    "AdvancedRateLimiter",
    "RateLimitDecision",
    "TierLimit",
    "create_rate_limit_decorator",
    "get_rate_limiter",
    "init_rate_limiter",
    "rate_limit",
    "reset_rate_limiter",
]
