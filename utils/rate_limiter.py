"""
utils/rate_limiter.py — COMPATIBILITY SHIM
==========================================

The real implementation now lives in ``core/rate_limiter.py``. This module is
kept so existing imports keep working:

    from utils.rate_limiter import RateLimiter

The canonical ``RateLimiter`` is a drop-in superset of the old one:
``RateLimiter(redis_client)`` and ``await rl.check_rate_limit(user_id, tier)``
behave the same (the latter still returns ``(is_limited, info)``), but tiers,
windows, fail-safe fallback and observability are all dramatically improved.

Do NOT add new logic here — extend ``core/rate_limiter.py`` instead.
"""

from __future__ import annotations

from core.rate_limiter import RateLimiter, get_rate_limiter, init_rate_limiter  # noqa: F401

__all__ = ["RateLimiter", "get_rate_limiter", "init_rate_limiter"]
