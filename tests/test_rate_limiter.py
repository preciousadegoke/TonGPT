"""
tests/test_rate_limiter.py — verification for the canonical rate limiter.

Runnable two ways:
    pytest tests/test_rate_limiter.py -v
    python tests/test_rate_limiter.py          # no pytest required

Covers:
  * fail-SAFE fallback when Redis is unavailable (conservative 5/min)
  * per-tier limits (free minute window denies the 4th request)
  * unlimited daily window (elite)
  * legacy (is_limited, info) adapter
  * read-only get_quota_status does NOT consume quota
  * the decorator resolves the limiter at CALL time (the P0 regression test)
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# Make the project root importable when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import rate_limiter as rl  # noqa: E402


# --------------------------------------------------------------------------- #
# Minimal in-memory fake Redis (only the ops the limiter uses).
# --------------------------------------------------------------------------- #
class FakeRedis:
    def __init__(self):
        self.z = {}  # key -> {member: score}

    # sorted sets ---------------------------------------------------------
    def zadd(self, key, mapping):
        self.z.setdefault(key, {}).update(mapping)
        return len(mapping)

    def zremrangebyscore(self, key, mn, mx):
        d = self.z.get(key, {})
        victims = [m for m, s in d.items() if mn <= s <= mx]
        for m in victims:
            del d[m]
        return len(victims)

    def zcard(self, key):
        return len(self.z.get(key, {}))

    def zcount(self, key, mn, mx):
        return sum(1 for s in self.z.get(key, {}).values() if mn <= s <= mx)

    def zrange(self, key, start, stop, withscores=False):
        items = sorted(self.z.get(key, {}).items(), key=lambda kv: kv[1])
        stop = len(items) - 1 if stop == -1 else stop
        sliced = items[start:stop + 1]
        return sliced if withscores else [m for m, _ in sliced]

    def expire(self, key, seconds):
        return True

    def exists(self, key):
        return 1 if key in self.z else 0

    # pipeline ------------------------------------------------------------
    def pipeline(self, transaction=True):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis):
        self.r = redis
        self.ops = []

    def __getattr__(self, name):
        def _record(*args, **kwargs):
            self.ops.append((name, args, kwargs))
            return self
        return _record

    def execute(self):
        results = []
        for name, args, kwargs in self.ops:
            results.append(getattr(self.r, name)(*args, **kwargs))
        self.ops.clear()
        return results


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _fresh(redis=None, **env):
    """Reset the singleton and build a limiter with a clean env."""
    for k in list(os.environ):
        if k.startswith("RATE_LIMIT_"):
            del os.environ[k]
    os.environ.update({k: str(v) for k, v in env.items()})
    rl.reset_rate_limiter()
    return rl.RateLimiter(redis)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
async def test_fallback_is_failsafe_not_failopen():
    limiter = _fresh(redis=None, RATE_LIMIT_FALLBACK_PER_MIN=5)
    allowed = 0
    for _ in range(8):
        d = await limiter.check(1, "pro", "ai_queries")
        allowed += 1 if d.allowed else 0
    assert allowed == 5, f"expected 5 allowed in fallback, got {allowed}"
    print("✓ fail-safe fallback caps at 5/min when Redis is down")


async def test_per_tier_minute_limit():
    r = FakeRedis()
    limiter = _fresh(redis=r, RATE_LIMIT_FREE_PER_MIN=3,
                     RATE_LIMIT_FREE_PER_HOUR=100, RATE_LIMIT_FREE_PER_DAY=100)
    results = [(await limiter.check(42, "free", "ai_queries")).allowed for _ in range(4)]
    assert results == [True, True, True, False], results
    print("✓ free tier: 3 allowed then 4th denied (minute window)")


async def test_tier_isolation_and_aliases():
    r = FakeRedis()
    limiter = _fresh(redis=r, RATE_LIMIT_FREE_PER_MIN=2, RATE_LIMIT_PRO_PER_MIN=5)
    # "premium" is a legacy alias -> pro (5/min), must NOT collapse to free (2).
    allowed = 0
    for _ in range(5):
        if (await limiter.check(7, "premium", "ai_queries")).allowed:
            allowed += 1
    assert allowed == 5, f"premium alias should map to pro (5/min), got {allowed}"
    print("✓ legacy alias premium->pro keeps higher limit (no silent downgrade)")


async def test_elite_unlimited_day():
    r = FakeRedis()
    limiter = _fresh(redis=r, RATE_LIMIT_ELITE_PER_MIN=1000,
                     RATE_LIMIT_ELITE_PER_HOUR=100000, RATE_LIMIT_ELITE_PER_DAY=-1)
    allowed = 0
    for _ in range(50):
        if (await limiter.check(9, "elite", "ai_queries")).allowed:
            allowed += 1
    assert allowed == 50
    print("✓ elite unlimited daily window allows all 50")


async def test_legacy_tuple_adapter():
    r = FakeRedis()
    limiter = _fresh(redis=r, RATE_LIMIT_FREE_PER_MIN=1)
    is_limited1, _ = await limiter.check_rate_limit(11, "free")
    is_limited2, info = await limiter.check_rate_limit(11, "free")
    assert is_limited1 is False and is_limited2 is True
    assert "error" in info
    print("✓ legacy check_rate_limit returns (is_limited, info) correctly")


async def test_quota_status_is_readonly():
    r = FakeRedis()
    limiter = _fresh(redis=r, RATE_LIMIT_FREE_PER_MIN=3)
    await limiter.check(5, "free", "ai_queries")  # consume 1
    before = await limiter.get_quota_status(5, "free", "ai_queries")
    after = await limiter.get_quota_status(5, "free", "ai_queries")
    assert before["windows"]["minute"]["used"] == 1
    assert after["windows"]["minute"]["used"] == 1, "get_quota_status must not consume"
    print("✓ get_quota_status is read-only (does not consume quota)")


async def test_decorator_resolves_limiter_at_call_time():
    """The P0 regression test: decorator applied BEFORE init must still limit."""
    r = FakeRedis()
    rl.reset_rate_limiter()
    for k in list(os.environ):
        if k.startswith("RATE_LIMIT_"):
            del os.environ[k]
    os.environ["RATE_LIMIT_FREE_PER_MIN"] = "1"

    calls = {"n": 0}

    @rl.create_rate_limit_decorator("ai_queries")
    async def handler(message):
        calls["n"] += 1

    # Decorator is applied while NO limiter exists yet (mirrors import order).
    assert rl.get_rate_limiter() is None

    # Now initialize (mirrors main() running before polling).
    rl.init_rate_limiter(r)

    class Msg:
        class _U:
            id = 123
        from_user = _U()
        async def reply(self, *a, **k):
            pass

    m = Msg()
    await handler(m)   # allowed
    await handler(m)   # should be rate-limited (free=1/min) -> handler NOT called
    assert calls["n"] == 1, f"expected exactly 1 handler call, got {calls['n']}"
    print("✓ decorator resolves limiter at call time (handler limited after init)")


ALL_TESTS = [
    test_fallback_is_failsafe_not_failopen,
    test_per_tier_minute_limit,
    test_tier_isolation_and_aliases,
    test_elite_unlimited_day,
    test_legacy_tuple_adapter,
    test_quota_status_is_readonly,
    test_decorator_resolves_limiter_at_call_time,
]


async def _run_all():
    for t in ALL_TESTS:
        await t()
    print("\nAll rate limiter tests passed ✅")


# pytest entry points (async wrappers)
def test_all_pytest():
    asyncio.run(_run_all())


if __name__ == "__main__":
    asyncio.run(_run_all())
