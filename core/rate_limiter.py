"""
core/rate_limiter.py — TonGPT canonical rate limiter (P0 fix)
============================================================

WHY THIS FILE EXISTS
--------------------
Before this module, rate limiting was effectively non-functional for the most
expensive endpoint (GPT/AI queries) for two reasons:

  1. The limiter singleton was created in ``main.on_startup()``, but handlers
     (e.g. ``handlers/gpt_reply.py``) were registered at *import time* — so the
     rate-limit decorator saw ``None`` and silently skipped limiting forever.

  2. The previous ``AdvancedRateLimiter`` was constructed with the
     ``SafeRedisClient`` wrapper, which does not implement ``pipeline``,
     ``zcard``, ``zremrangebyscore``, ``setex`` or ``keys`` — so even when it
     *was* wired up it raised ``AttributeError`` and fell into a broken state.

On top of that there were THREE different limiter implementations with three
different tier vocabularies (``free/basic/premium`` vs ``free/starter/pro/...``).

This module is the single source of truth. It is:

  * **Call-time resolved** — the decorator resolves the live limiter every call,
    so initialization order can never silently disable limiting again.
  * **Raw-Redis aware** — it transparently unwraps ``SafeRedisClient`` to talk to
    the underlying ``redis.Redis`` and uses an atomic sorted-set sliding window.
  * **Fail-SAFE, not fail-open** — if Redis is unavailable it does NOT allow
    unlimited traffic; it falls back to a conservative in-process limit
    (default 5 requests/minute/user) so an outage can't become a cost incident.
  * **Per-tier** — limits map to the real subscription tiers
    (free/starter/pro/pro_plus/elite), env-tunable, with legacy aliases.
  * **Observable** — every limit hit is logged via structlog with user_id, tier,
    endpoint, the window that tripped, and retry_after.

Backward compatibility
-----------------------
``core/rate_limiting.py`` and ``utils/rate_limiter.py`` are now thin shims that
re-export from here, so existing imports keep working:

    from core.rate_limiting import get_rate_limiter, create_rate_limit_decorator
    from utils.rate_limiter import RateLimiter

Public surface
--------------
    init_rate_limiter(redis_client)            -> RateLimiter   (idempotent)
    get_rate_limiter(redis_client=None)        -> RateLimiter | None
    create_rate_limit_decorator(endpoint)      -> decorator     (call-time safe)
    rate_limit(endpoint)                       -> alias of the above

    RateLimiter.check(user_id, tier, endpoint) -> RateLimitDecision  (consumes)
    RateLimiter.check_rate_limit(uid, tier)    -> (is_limited, info) (legacy API)
    RateLimiter.get_quota_status(uid, tier)    -> dict            (read-only)
    RateLimiter.get_user_risk_score(...)       -> (score, tier_name)
"""

from __future__ import annotations

import asyncio
import functools
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional, Tuple

import structlog

log = structlog.get_logger(__name__)


# --------------------------------------------------------------------------- #
# Environment helpers
# --------------------------------------------------------------------------- #
def _env_int(name: str, default: int) -> int:
    """Read a positive int from the environment; fall back to ``default``.

    ``-1`` is allowed and means "unlimited" for daily caps.
    """
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("rate_limit_bad_env", var=name, value=raw, fallback=default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# --------------------------------------------------------------------------- #
# Tier limits
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TierLimit:
    """Per-tier ceilings. ``per_day = -1`` means unlimited daily."""

    per_minute: int
    per_hour: int
    per_day: int  # -1 == unlimited


def _load_tier_limits() -> Dict[str, TierLimit]:
    """Build the tier table from defaults, overridable via env vars.

    Daily caps intentionally mirror the subscription system's
    ``queries_per_day`` (handlers/pay.py): 100 / 500 / 1000 / unlimited.
    """
    return {
        "free": TierLimit(
            per_minute=_env_int("RATE_LIMIT_FREE_PER_MIN", 3),
            per_hour=_env_int("RATE_LIMIT_FREE_PER_HOUR", 15),
            per_day=_env_int("RATE_LIMIT_FREE_PER_DAY", 25),
        ),
        "starter": TierLimit(
            per_minute=_env_int("RATE_LIMIT_STARTER_PER_MIN", 10),
            per_hour=_env_int("RATE_LIMIT_STARTER_PER_HOUR", 100),
            per_day=_env_int("RATE_LIMIT_STARTER_PER_DAY", 100),
        ),
        "pro": TierLimit(
            per_minute=_env_int("RATE_LIMIT_PRO_PER_MIN", 20),
            per_hour=_env_int("RATE_LIMIT_PRO_PER_HOUR", 300),
            per_day=_env_int("RATE_LIMIT_PRO_PER_DAY", 500),
        ),
        "pro_plus": TierLimit(
            per_minute=_env_int("RATE_LIMIT_PRO_PLUS_PER_MIN", 30),
            per_hour=_env_int("RATE_LIMIT_PRO_PLUS_PER_HOUR", 600),
            per_day=_env_int("RATE_LIMIT_PRO_PLUS_PER_DAY", 1000),
        ),
        "elite": TierLimit(
            per_minute=_env_int("RATE_LIMIT_ELITE_PER_MIN", 60),
            per_hour=_env_int("RATE_LIMIT_ELITE_PER_HOUR", 2000),
            per_day=_env_int("RATE_LIMIT_ELITE_PER_DAY", -1),  # unlimited
        ),
    }


# Legacy tier names → canonical tier names. Keeps old callers working and stops
# a "pro"/"premium" user from being silently dropped to free limits.
_TIER_ALIASES = {
    "basic": "starter",
    "premium": "pro",
    "pro+": "pro_plus",
    "proplus": "pro_plus",
    "": "free",
    "none": "free",
    "error": "free",  # engine unreachable -> treat as free (conservative)
}

# Window definitions shared by every check: (name, seconds, attr_on_TierLimit)
_WINDOWS: Tuple[Tuple[str, int, str], ...] = (
    ("minute", 60, "per_minute"),
    ("hour", 3600, "per_hour"),
    ("day", 86400, "per_day"),
)


# --------------------------------------------------------------------------- #
# Decision object
# --------------------------------------------------------------------------- #
@dataclass
class RateLimitDecision:
    """Outcome of a rate-limit check."""

    allowed: bool
    tier: str
    endpoint: str
    limit: int = 0          # the ceiling of the window that mattered
    remaining: int = 0      # remaining in the most-restrictive window
    retry_after: int = 0    # seconds until the user may retry (when blocked)
    window: str = ""        # which window tripped ("minute"/"hour"/"day")
    degraded: bool = False  # True when Redis was down and fallback was used

    def user_message(self) -> str:
        """Friendly, HTML-formatted message to show a blocked user."""
        if self.degraded:
            return (
                "⏳ <b>Slow down a moment</b>\n\n"
                "We're running in safe mode right now and limiting requests to "
                "keep things stable. Please try again in a minute."
            )
        mins = max(1, self.retry_after // 60)
        unit = "minute" if mins == 1 else "minutes"
        return (
            "⏰ <b>Rate limit reached</b>\n\n"
            f"You've hit your <b>{self.tier.title()}</b> plan limit for this "
            f"({self.window}) window.\n"
            f"Try again in about {mins} {unit}, or use /upgrade for higher limits."
        )


# --------------------------------------------------------------------------- #
# The limiter
# --------------------------------------------------------------------------- #
class RateLimiter:
    """Async, tier-aware sliding-window rate limiter.

    Construct once (via :func:`init_rate_limiter`) and reuse. All public methods
    are coroutine-safe. Redis I/O (the redis-py client is synchronous) is run in
    a worker thread so the event loop is never blocked.
    """

    def __init__(self, redis_client: Optional[object] = None) -> None:
        # Unwrap SafeRedisClient (and any similar wrapper) to reach the real
        # redis.Redis. We need raw pipeline/zset operations the wrapper lacks.
        self._raw = self._resolve_raw(redis_client)

        self.enabled = _env_bool("RATE_LIMIT_ENABLED", True)
        self.tier_limits = _load_tier_limits()

        # Conservative ceiling used ONLY when Redis is unavailable. Fail-safe,
        # not fail-open: we'd rather throttle than hand out unlimited GPT calls.
        self.fallback_per_minute = _env_int("RATE_LIMIT_FALLBACK_PER_MIN", 5)

        # In-process fallback store: user_id -> deque[timestamps] (last minute).
        self._mem: Dict[Any, Deque[float]] = defaultdict(deque)
        self._mem_lock = asyncio.Lock()

        # Tiny in-process tier cache so we don't hit the engine on every message.
        self._tier_cache: Dict[Any, Tuple[str, float]] = {}
        self._tier_ttl = _env_int("RATE_LIMIT_TIER_CACHE_TTL", 60)

        log.info(
            "rate_limiter_initialized",
            enabled=self.enabled,
            redis=bool(self._raw),
            fallback_per_minute=self.fallback_per_minute,
            tiers=list(self.tier_limits.keys()),
        )

    # ----- construction helpers ------------------------------------------- #
    @staticmethod
    def _resolve_raw(client: Optional[object]) -> Optional[object]:
        """Return the underlying redis.Redis, unwrapping known wrappers."""
        if client is None:
            return None
        inner = getattr(client, "client", None)
        return inner if inner is not None else client

    def normalize_tier(self, tier: Optional[str]) -> str:
        """Map any incoming tier string to a known canonical tier name."""
        t = (tier or "free").strip().lower()
        t = _TIER_ALIASES.get(t, t)
        return t if t in self.tier_limits else "free"

    def _limits_for(self, tier: str) -> TierLimit:
        return self.tier_limits[self.normalize_tier(tier)]

    @staticmethod
    def _key(user_id: Any, endpoint: str, window: str) -> str:
        return f"rl:{endpoint}:{user_id}:{window}"

    # ----- Redis sliding window ------------------------------------------- #
    def _peek_redis(self, key: str, window_seconds: int, now: float) -> Tuple[int, int]:
        """Purge expired entries and return (count, retry_after_seconds).

        Read-only with respect to consumption: it does NOT add the current
        request. This lets us check every window first and only consume when
        ALL windows pass (so a denied request never leaks a slot).
        """
        pipe = self._raw.pipeline()
        pipe.zremrangebyscore(key, 0, now - window_seconds)
        pipe.zcard(key)
        pipe.zrange(key, 0, 0, withscores=True)  # oldest entry, for retry calc
        results = pipe.execute()
        count = int(results[1] or 0)
        oldest = results[2]
        retry_after = window_seconds
        if oldest:
            oldest_score = oldest[0][1]
            retry_after = max(1, int(window_seconds - (now - oldest_score)))
        return count, retry_after

    def _commit_redis(self, user_id: Any, endpoint: str, now: float) -> None:
        """Atomically record one request in every window's sorted set."""
        member = f"{now:.6f}:{os.urandom(4).hex()}"
        pipe = self._raw.pipeline()
        for window, seconds, _attr in _WINDOWS:
            key = self._key(user_id, endpoint, window)
            pipe.zadd(key, {member: now})
            pipe.expire(key, seconds + 5)  # small grace so TTL covers the window
        pipe.execute()

    # ----- in-process fallback (Redis down) ------------------------------- #
    async def _check_memory_fallback(
        self, user_id: Any, tier: str, endpoint: str
    ) -> RateLimitDecision:
        """Conservative per-minute limiter used when Redis is unavailable."""
        now = time.time()
        cutoff = now - 60
        async with self._mem_lock:
            bucket = self._mem[user_id]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            count = len(bucket)
            if count >= self.fallback_per_minute:
                retry = max(1, int(60 - (now - bucket[0]))) if bucket else 60
                log.warning(
                    "rate_limit_hit",
                    user_id=user_id,
                    tier=tier,
                    endpoint=endpoint,
                    window="minute",
                    mode="fallback",
                    limit=self.fallback_per_minute,
                    retry_after=retry,
                )
                return RateLimitDecision(
                    allowed=False, tier=tier, endpoint=endpoint,
                    limit=self.fallback_per_minute, remaining=0,
                    retry_after=retry, window="minute", degraded=True,
                )
            bucket.append(now)
            # RLIM-002: bound memory — drop now-empty buckets when the map is large.
            if len(self._mem) > 10000:
                for k in [k for k, v in self._mem.items() if not v][:2000]:
                    self._mem.pop(k, None)
            return RateLimitDecision(
                allowed=True, tier=tier, endpoint=endpoint,
                limit=self.fallback_per_minute,
                remaining=self.fallback_per_minute - count - 1,
                window="minute", degraded=True,
            )

    # ----- atomic check+consume (RLIM-001) -------------------------------- #
    # The previous design peeked all windows, then committed in a SEPARATE
    # pipeline. Concurrent requests could all pass the peek before any committed,
    # so a user could exceed the cap by firing requests in parallel. This Lua
    # script runs ENTIRELY inside Redis (atomically): it checks every window and
    # only consumes a slot in each if ALL windows pass — no peek/commit gap.
    _ATOMIC_LUA = """
    local now = tonumber(ARGV[1])
    local member = ARGV[2]
    local n = (#ARGV - 2) / 2
    local tightest_remaining = -1
    local tightest_limit = 0
    for i=1,n do
        local key = KEYS[i]
        local seconds = tonumber(ARGV[1 + i*2])
        local limit = tonumber(ARGV[2 + i*2])
        if limit >= 0 then
            redis.call('ZREMRANGEBYSCORE', key, 0, now - seconds)
            local count = redis.call('ZCARD', key)
            if count >= limit then
                local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
                local retry = seconds
                if oldest[2] then
                    retry = math.ceil(seconds - (now - tonumber(oldest[2])))
                    if retry < 1 then retry = 1 end
                end
                return {0, retry, i, 0, 0}
            end
            local remaining = limit - count - 1
            if tightest_remaining < 0 or remaining < tightest_remaining then
                tightest_remaining = remaining
                tightest_limit = limit
            end
        end
    end
    for i=1,n do
        local key = KEYS[i]
        local seconds = tonumber(ARGV[1 + i*2])
        local limit = tonumber(ARGV[2 + i*2])
        if limit >= 0 then
            redis.call('ZADD', key, now, member)
            redis.call('EXPIRE', key, seconds + 5)
        end
    end
    if tightest_remaining < 0 then tightest_remaining = 0 end
    return {1, 0, 0, tightest_remaining, tightest_limit}
    """

    def _atomic_check(self, user_id: Any, endpoint: str, limits: "TierLimit", now: float):
        keys = [self._key(user_id, endpoint, w) for w, _s, _a in _WINDOWS]
        member = f"{now:.6f}:{os.urandom(4).hex()}"
        argv = [now, member]
        for _w, seconds, attr in _WINDOWS:
            argv += [seconds, getattr(limits, attr)]
        res = self._raw.eval(self._ATOMIC_LUA, len(keys), *keys, *argv)
        # res = [allowed, retry_after, window_index, tightest_remaining, tightest_limit]
        return [int(x) for x in res]

    # ----- public: check + consume ---------------------------------------- #
    async def check(
        self, user_id: Any, tier: str = "free", endpoint: str = "ai_queries"
    ) -> RateLimitDecision:
        """Check and, if allowed, consume one unit of quota — ATOMICALLY.

        Never raises. On any Redis error it degrades to the conservative
        in-process fallback rather than failing open.
        """
        if not self.enabled:
            return RateLimitDecision(allowed=True, tier=self.normalize_tier(tier), endpoint=endpoint)

        tier = self.normalize_tier(tier)
        limits = self._limits_for(tier)
        now = time.time()

        # No usable Redis -> conservative fallback.
        if not self._raw:
            return await self._check_memory_fallback(user_id, tier, endpoint)

        try:
            allowed, retry_after, win_idx, remaining, limit = await asyncio.to_thread(
                self._atomic_check, user_id, endpoint, limits, now
            )
            if not allowed:
                window = _WINDOWS[win_idx - 1][0] if 1 <= win_idx <= len(_WINDOWS) else ""
                log.warning(
                    "rate_limit_hit",
                    user_id=user_id, tier=tier, endpoint=endpoint,
                    window=window, mode="redis_atomic", retry_after=retry_after,
                )
                return RateLimitDecision(
                    allowed=False, tier=tier, endpoint=endpoint,
                    limit=limit, remaining=0, retry_after=retry_after, window=window,
                )
            log.debug("rate_limit_ok", user_id=user_id, tier=tier, endpoint=endpoint, remaining=remaining)
            return RateLimitDecision(
                allowed=True, tier=tier, endpoint=endpoint,
                limit=limit, remaining=max(0, remaining),
            )
        except Exception as e:  # noqa: BLE001 - never let limiter crash a handler
            log.warning("rate_limit_redis_error_degraded", err=str(e), user_id=user_id)
            return await self._check_memory_fallback(user_id, tier, endpoint)

    # ----- public: read-only status (for /status) ------------------------- #
    async def get_quota_status(
        self, user_id: Any, tier: str = "free", endpoint: str = "ai_queries"
    ) -> Dict[str, Any]:
        """Return current usage per window WITHOUT consuming quota."""
        tier = self.normalize_tier(tier)
        limits = self._limits_for(tier)
        now = time.time()
        out: Dict[str, Any] = {"tier": tier, "endpoint": endpoint, "degraded": not self._raw, "windows": {}}

        if not self._raw:
            # Fallback mode: only the per-minute global limit is meaningful.
            async with self._mem_lock:
                bucket = self._mem.get(user_id, deque())
                used = sum(1 for t in bucket if t > now - 60)
            out["windows"]["minute"] = {
                "used": used,
                "limit": self.fallback_per_minute,
                "remaining": max(0, self.fallback_per_minute - used),
            }
            return out

        try:
            for window, seconds, attr in _WINDOWS:
                limit = getattr(limits, attr)
                key = self._key(user_id, endpoint, window)
                count, _ = await asyncio.to_thread(self._peek_redis, key, seconds, now)
                out["windows"][window] = {
                    "used": count,
                    "limit": "∞" if limit < 0 else limit,
                    "remaining": "∞" if limit < 0 else max(0, limit - count),
                }
        except Exception as e:  # noqa: BLE001
            log.debug("quota_status_error", err=str(e))
            out["error"] = "unavailable"
        return out

    # ----- backward-compatible legacy API --------------------------------- #
    async def check_rate_limit(
        self, user_id: Any, tier: str = "free", endpoint: str = "ai_queries"
    ) -> Tuple[bool, Dict[str, Any]]:
        """Legacy adapter used by bot/commands.py and old utils.RateLimiter.

        Returns ``(is_limited, info)`` where ``is_limited`` is True when the
        request should be DENIED (note the inverted boolean vs ``check``).
        """
        d = await self.check(user_id, tier, endpoint)
        info = {
            "tier": d.tier,
            "limit": d.limit,
            "remaining": d.remaining,
            "reset_time": int(time.time()) + d.retry_after,
            "window": d.window,
            "degraded": d.degraded,
        }
        if not d.allowed:
            info["error"] = "Rate limit exceeded"
        return (not d.allowed), info

    # ----- risk scoring (ported, degrades gracefully) --------------------- #
    async def get_user_risk_score(
        self, user_id: Any, tier: str = "free", ip_address: Optional[str] = None
    ) -> Tuple[int, str]:
        """Lightweight abuse heuristic. Returns (score 0-100, label).

        Reads counters best-effort; any failure yields a benign ("Trusted")
        score so risk scoring can never block legitimate traffic by itself.
        """
        if not self._raw:
            return 0, "Trusted"
        try:
            def _gather() -> Tuple[int, int, int]:
                now = time.time()
                pipe = self._raw.pipeline()
                # AI usage in the last hour and minute (our own keys).
                pipe.zcount(self._key(user_id, "ai_queries", "hour"), now - 3600, now)
                pipe.zcount(self._key(user_id, "ai_queries", "minute"), now - 60, now)
                pipe.exists(f"user_history:{user_id}")
                res = pipe.execute()
                return int(res[0] or 0), int(res[1] or 0), int(res[2] or 0)

            hour_ai, minute_ai, has_history = await asyncio.to_thread(_gather)

            score = 0
            if not has_history:
                score += 20
            if minute_ai > 10:
                score += 40
            elif minute_ai > 5:
                score += 20
            if hour_ai > 100:
                score += 30

            score = min(100, score)
            if score < 30:
                label = "Trusted"
            elif score < 60:
                label = "Watch"
            elif score < 80:
                label = "Suspicious"
            else:
                label = "High Risk"
            return score, label
        except Exception as e:  # noqa: BLE001
            log.debug("risk_score_error", err=str(e))
            return 0, "Trusted"


# --------------------------------------------------------------------------- #
# Module-level singleton + accessors
# --------------------------------------------------------------------------- #
_LIMITER: Optional[RateLimiter] = None


def init_rate_limiter(redis_client: Optional[object] = None) -> RateLimiter:
    """Create (or return the existing) global limiter. Idempotent.

    Call this ONCE during startup BEFORE any handler is registered.
    """
    global _LIMITER
    if _LIMITER is None:
        _LIMITER = RateLimiter(redis_client)
    return _LIMITER


def get_rate_limiter(redis_client: Optional[object] = None) -> Optional[RateLimiter]:
    """Return the global limiter, lazily creating it if a client is supplied.

    Passing ``redis_client`` keeps backward compatibility with the old
    ``get_rate_limiter(redis_client)`` initialization call in main.py.
    """
    global _LIMITER
    if _LIMITER is None and redis_client is not None:
        _LIMITER = RateLimiter(redis_client)
    return _LIMITER


def reset_rate_limiter() -> None:
    """Test hook: drop the singleton so the next init starts fresh."""
    global _LIMITER
    _LIMITER = None


# --------------------------------------------------------------------------- #
# Tier resolution (cached) used by the decorator
# --------------------------------------------------------------------------- #
async def _resolve_tier(limiter: RateLimiter, user_id: Any) -> str:
    """Resolve a user's subscription tier from the C# Engine, with a short cache.

    Falls back to 'free' on any error (conservative).
    """
    now = time.time()
    cached = limiter._tier_cache.get(user_id)
    if cached and cached[1] > now:
        return cached[0]
    tier = "free"
    try:
        from services.engine_client import engine_client
        status = await engine_client.get_user_status(str(user_id))
        tier = limiter.normalize_tier(status.get("plan") or status.get("tier") or "free")
    except Exception as e:  # noqa: BLE001
        log.debug("tier_resolve_failed", user_id=user_id, err=str(e))
    limiter._tier_cache[user_id] = (tier, now + limiter._tier_ttl)
    # RLIM-002: bound memory — evict expired entries when the cache grows large.
    if len(limiter._tier_cache) > 50000:
        for k in [k for k, (_t, exp) in list(limiter._tier_cache.items()) if exp <= now][:10000]:
            limiter._tier_cache.pop(k, None)
    return tier


# --------------------------------------------------------------------------- #
# Decorator — resolves the limiter AT CALL TIME (the core of the P0 fix)
# --------------------------------------------------------------------------- #
def create_rate_limit_decorator(endpoint: str = "ai_queries"):
    """Return a decorator that rate-limits an aiogram message handler.

    Crucially, the limiter and the user's tier are resolved INSIDE the wrapper
    (i.e. per call), so applying this decorator at import time — before the
    limiter exists — can never silently disable limiting.
    """

    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(message, *args, **kwargs):
            limiter = get_rate_limiter()

            # Not initialized yet (very early startup) -> allow but warn loudly,
            # so this shows up in logs rather than silently disabling limits.
            if limiter is None:
                log.warning("rate_limiter_missing_allow", endpoint=endpoint)
                return await handler(message, *args, **kwargs)

            if not limiter.enabled:
                return await handler(message, *args, **kwargs)

            try:
                user_id = message.from_user.id
            except AttributeError:
                # No user context (shouldn't happen for messages) -> don't block.
                return await handler(message, *args, **kwargs)

            tier = await _resolve_tier(limiter, user_id)
            decision = await limiter.check(user_id, tier, endpoint)

            if not decision.allowed:
                try:
                    await message.reply(decision.user_message(), parse_mode="HTML")
                except Exception as e:  # noqa: BLE001
                    log.debug("rate_limit_reply_failed", err=str(e))
                return None

            return await handler(message, *args, **kwargs)

        return wrapper

    return decorator


# Friendly alias.
rate_limit = create_rate_limit_decorator


__all__ = [
    "RateLimiter",
    "RateLimitDecision",
    "TierLimit",
    "init_rate_limiter",
    "get_rate_limiter",
    "reset_rate_limiter",
    "create_rate_limit_decorator",
    "rate_limit",
]
