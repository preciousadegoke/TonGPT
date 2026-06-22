"""
tests/test_ton_api_service.py — async TON service reliability + non-blocking.

Runnable two ways:
    pytest tests/test_ton_api_service.py -v
    python tests/test_ton_api_service.py

Covers:
  * wallet info success + whale classification + USD estimate
  * HTTP 429 retry-then-success
  * circuit breaker trips after repeated failures and serves STALE data
  * strict price RAISES on failure; best-effort price is safe (0.0 / last known)
  * NON-BLOCKING: 50 concurrent calls run concurrently (event loop not frozen)

Uses httpx.MockTransport so no network is touched.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from services.ton_api_service import TonApiService, TonApiError  # noqa: E402


def _svc(handler, **overrides):
    """Build a service backed by a MockTransport handler."""
    for k in list(os.environ):
        if k.startswith("TON_") or k.startswith("COINGECKO"):
            del os.environ[k]
    os.environ.update({k: str(v) for k, v in overrides.items()})
    s = TonApiService()
    s.base_url = "https://tonapi.test/v2"
    s.coingecko_url = "https://coingecko.test/api/v3"
    s._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return s


def _price_response():
    return httpx.Response(200, json={"the-open-network": {"usd": 2.5}})


# --------------------------------------------------------------------------- #
async def test_wallet_info_success():
    def handler(request):
        if "/simple/price" in request.url.path:
            return _price_response()
        if "/accounts/" in request.url.path:
            return httpx.Response(200, json={"balance": "5000000000000", "last_activity": 1700000000})
        return httpx.Response(404)

    s = _svc(handler)
    info = await s.get_wallet_info("EQabc")
    assert info.get("error") is None
    assert info["balance_ton"] == 5000.0
    assert info["whale_category"] == "small_whale"   # 5000 TON >= 1000
    assert abs(info["balance_usd"] - 5000.0 * 2.5) < 1e-6
    await s.aclose()
    print("✓ wallet info success: balance, whale category, USD estimate")


async def test_429_retry_then_success():
    calls = {"n": 0}

    def handler(request):
        if "/accounts/" in request.url.path:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429)
            return httpx.Response(200, json={"balance": "0"})
        if "/simple/price" in request.url.path:
            return _price_response()
        return httpx.Response(404)

    s = _svc(handler, TON_HTTP_MAX_RETRIES=3, TON_HTTP_BACKOFF_BASE=0.001, TON_HTTP_BACKOFF_CAP=0.01)
    info = await s.get_wallet_info("EQretry")
    assert info.get("error") is None
    assert calls["n"] == 2, f"expected 1 retry after 429, got {calls['n']} calls"
    await s.aclose()
    print("✓ HTTP 429 is retried and then succeeds")


async def test_breaker_trips_and_serves_stale():
    mode = {"ok": True}

    def handler(request):
        if "/simple/price" in request.url.path:
            return _price_response()
        if "/accounts/" in request.url.path:
            if mode["ok"]:
                return httpx.Response(200, json={"balance": "2000000000000"})  # 2000 TON
            return httpx.Response(500)
        return httpx.Response(404)

    s = _svc(handler, TON_HTTP_MAX_RETRIES=1, TON_BREAKER_THRESHOLD=2,
             TON_BREAKER_COOLDOWN=30, TON_HTTP_BACKOFF_BASE=0.001)

    # Prime a successful result so we have stale data cached.
    good = await s.get_wallet_info("EQstale")
    assert good["balance_ton"] == 2000.0

    # Upstream now fails for every request.
    mode["ok"] = False
    r1 = await s.get_wallet_info("EQstale")  # failure #1 -> served stale
    r2 = await s.get_wallet_info("EQstale")  # failure #2 -> breaker trips, served stale
    assert r1.get("stale") is True and r2.get("stale") is True
    assert s._breakers["accounts"].is_open(time.time()), "breaker should be open after threshold"

    # While open, a fresh address (no stale) returns an error quickly (no network).
    r3 = await s.get_wallet_info("EQnostale")
    assert "error" in r3
    await s.aclose()
    print("✓ breaker trips after repeated failures and serves stale data")


async def test_price_strict_vs_best_effort():
    state = {"ok": False}

    def handler(request):
        if "/simple/price" in request.url.path:
            if state["ok"]:
                return _price_response()
            return httpx.Response(500)
        return httpx.Response(404)

    s = _svc(handler)
    # Strict price must RAISE when it can't get a fresh price (payment safety).
    raised = False
    try:
        await s.get_ton_price_usd()
    except Exception:
        raised = True
    assert raised, "strict price must raise on failure (never hardcode)"
    # Best-effort returns 0.0 when there's no cached price yet.
    assert await s.get_ton_price_best_effort() == 0.0

    # Once a good price is cached, best-effort returns it even if upstream dies.
    state["ok"] = True
    p = await s.get_ton_price_usd()
    assert p == 2.5
    state["ok"] = False
    assert await s.get_ton_price_best_effort() == 2.5  # last known
    await s.aclose()
    print("✓ strict price raises; best-effort is safe (0.0 / last known)")


async def test_nonblocking_concurrency():
    """50 concurrent calls must run concurrently — proves the loop isn't frozen."""
    s = TonApiService()

    async def fake_request(path, *, group, params=None, user_id=None):
        await asyncio.sleep(0.05)  # simulated upstream latency (non-blocking)
        return {"balance": "1000000000000", "last_activity": 0}

    async def fake_price():
        return 2.0

    s._request = fake_request          # type: ignore[assignment]
    s.get_ton_price_best_effort = fake_price  # type: ignore[assignment]

    start = time.perf_counter()
    results = await asyncio.gather(*[s.get_wallet_info(f"EQ{i}") for i in range(50)])
    elapsed = time.perf_counter() - start

    assert all(r["balance_ton"] == 1000.0 for r in results)
    # If calls were blocking/serialized this would be ~50*0.05 = 2.5s. Concurrent
    # execution finishes in ~0.05s; allow generous headroom.
    assert elapsed < 1.0, f"calls did not run concurrently (elapsed={elapsed:.2f}s)"
    print(f"✓ 50 concurrent calls non-blocking (elapsed={elapsed*1000:.0f}ms, serial would be ~2500ms)")


ALL = [
    test_wallet_info_success,
    test_429_retry_then_success,
    test_breaker_trips_and_serves_stale,
    test_price_strict_vs_best_effort,
    test_nonblocking_concurrency,
]


async def _run_all():
    for t in ALL:
        await t()
    print("\nAll TON API service tests passed ✅")


def test_all_pytest():
    asyncio.run(_run_all())


if __name__ == "__main__":
    asyncio.run(_run_all())
