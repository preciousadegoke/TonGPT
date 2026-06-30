"""
services/ton_api_service.py — fully async TON data service (P1 reliability fix).

WHY
---
The old services/tonapi.py used synchronous `requests` + `time.sleep()` inside
async handlers. Every TONAPI call blocked the entire aiogram event loop, so one
slow upstream request froze the bot for ALL users. This module replaces that
with a single shared httpx.AsyncClient and proper async resilience.

WHAT YOU GET
------------
* ONE shared httpx.AsyncClient (connection pooling, keep-alive, bounded
  concurrency, env-configurable timeouts). Created in main.py at startup and
  closed on shutdown; lazily created if used before startup.
* Async retry with exponential backoff + jitter; honours HTTP 429 `Retry-After`.
* Per-endpoint-group circuit breaker: after N consecutive failures a group is
  "open" for a cooldown, during which we serve cached/stale data instead of
  hammering a dead upstream.
* Graceful stale-cache fallback for wallet info and whale summaries.
* Strict, never-hardcoded TON/USD price for PAYMENTS (raises if it can't get a
  fresh-enough price) plus a separate best-effort price for display.
* structlog tracing: every request logs path, status, duration_ms, attempt.
* Per-user hourly quota guard (best-effort via Redis), run off-thread so it
  never blocks the loop.

This module returns the SAME dict shapes the old tonapi.py returned, so callers
keep working; the legacy module is now a thin async shim over this one.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx
import structlog

log = structlog.get_logger(__name__)


# --------------------------------------------------------------------------- #
# Config (env-tunable). Read once at construction; cheap to re-create for tests.
# --------------------------------------------------------------------------- #
def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class _Breaker:
    """Circuit-breaker state for one endpoint group."""
    failures: int = 0
    open_until: float = 0.0

    def is_open(self, now: float) -> bool:
        return now < self.open_until


class TonApiError(Exception):
    """Raised when a TONAPI request ultimately fails (after retries/breaker)."""


class TonApiService:
    """Async TON data client. Construct once; reuse the singleton `ton_service`."""

    def __init__(self) -> None:
        self.base_url = (os.getenv("TONAPI_BASE_URL") or "https://tonapi.io/v2").rstrip("/")
        self.api_key = os.getenv("TONAPI_KEY")
        self.timeout = _f("TON_HTTP_TIMEOUT", 10.0)
        self.max_retries = _i("TON_HTTP_MAX_RETRIES", 3)
        self.backoff_base = _f("TON_HTTP_BACKOFF_BASE", 0.5)
        self.backoff_cap = _f("TON_HTTP_BACKOFF_CAP", 8.0)
        self.breaker_threshold = _i("TON_BREAKER_THRESHOLD", 5)
        self.breaker_cooldown = _f("TON_BREAKER_COOLDOWN", 30.0)
        self.price_ttl = _f("TON_PRICE_CACHE_TTL", 60.0)
        self.stale_ttl = _f("TON_STALE_CACHE_TTL", 900.0)  # serve stale up to 15 min
        self.user_quota_per_hour = _i("TON_USER_QUOTA_PER_HOUR", 100)
        self.coingecko_url = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3")
        self.coingecko_id = os.getenv("COINGECKO_TON_ID", "the-open-network")

        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()
        self._breakers: Dict[str, _Breaker] = {}
        self._stale: Dict[str, tuple] = {}          # key -> (value, ts)
        self._price_cache: Dict[str, Any] = {"price": None, "ts": 0.0}

        self.whale_thresholds = {
            "small_whale": 1000, "medium_whale": 10000,
            "large_whale": 100000, "mega_whale": 1000000,
        }

    # ----- client lifecycle ---------------------------------------------- #
    async def startup(self) -> None:
        """Create the shared client. Safe to call once at app startup."""
        await self._get_client()
        log.info("ton_api_service_started", base_url=self.base_url, timeout=self.timeout,
                 max_retries=self.max_retries, breaker_threshold=self.breaker_threshold)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None and not self._client.is_closed:
            return self._client
        async with self._client_lock:
            if self._client is None or self._client.is_closed:
                headers = {"Accept": "application/json", "User-Agent": "TonGPT-Bot/1.0"}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                self._client = httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout),
                    headers=headers,
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            log.info("ton_api_service_closed")

    # ----- stale cache helpers ------------------------------------------- #
    def _stale_set(self, key: str, value: Any) -> None:
        self._stale[key] = (value, time.time())

    def _stale_get(self, key: str) -> Optional[Any]:
        item = self._stale.get(key)
        if not item:
            return None
        value, ts = item
        if time.time() - ts > self.stale_ttl:
            return None
        return value

    # ----- per-user quota (best-effort, never blocks the loop) ----------- #
    async def _quota_ok(self, user_id: Optional[int]) -> bool:
        if not user_id or self.user_quota_per_hour <= 0:
            return True

        def _check() -> bool:
            try:
                from utils.redis_conn import redis_client
                rc = getattr(redis_client, "client", redis_client)
                if not rc:
                    return True
                key = f"tonapi_quota:{user_id}"
                count = rc.incr(key)
                if count == 1:
                    rc.expire(key, 3600)
                return count <= self.user_quota_per_hour
            except Exception:
                return True  # fail-open: quota is best-effort

        try:
            return await asyncio.to_thread(_check)
        except Exception:
            return True

    # ----- core request with retries + breaker --------------------------- #
    async def _request(
        self, path: str, *, group: str, params: Optional[dict] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """GET {base}{path} as JSON with retries, 429 handling and a breaker.

        Raises TonApiError on ultimate failure (caller decides stale fallback).
        """
        now = time.time()
        breaker = self._breakers.setdefault(group, _Breaker())
        if breaker.is_open(now):
            log.warning("ton_breaker_open", group=group, retry_in=round(breaker.open_until - now, 1))
            raise TonApiError(f"circuit breaker open for {group}")

        if not await self._quota_ok(user_id):
            log.warning("ton_user_quota_exceeded", user_id=user_id)
            raise TonApiError("per-user TON API quota exceeded")

        client = await self._get_client()
        url = f"{self.base_url}{path}"
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            started = time.perf_counter()
            try:
                resp = await client.get(url, params=params)
                dur_ms = round((time.perf_counter() - started) * 1000, 1)

                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    delay = float(retry_after) if (retry_after or "").isdigit() else self._backoff(attempt)
                    log.warning("ton_rate_limited", group=group, attempt=attempt, retry_after=delay, duration_ms=dur_ms)
                    if attempt < self.max_retries:
                        await asyncio.sleep(delay)
                        continue
                    raise TonApiError("429 rate limited")

                resp.raise_for_status()
                log.debug("ton_request_ok", group=group, path=path, status=resp.status_code,
                          duration_ms=dur_ms, attempt=attempt)
                self._record_success(group)
                return resp.json()

            except (httpx.HTTPStatusError, httpx.RequestError, TonApiError) as e:
                last_exc = e
                dur_ms = round((time.perf_counter() - started) * 1000, 1)
                log.warning("ton_request_error", group=group, path=path, attempt=attempt,
                            duration_ms=dur_ms, err=f"{type(e).__name__}: {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(self._backoff(attempt))
                    continue

        self._record_failure(group)
        raise TonApiError(f"{group} request failed after {self.max_retries} attempts: {last_exc}")

    def _backoff(self, attempt: int) -> float:
        delay = min(self.backoff_cap, self.backoff_base * (2 ** (attempt - 1)))
        return delay + random.uniform(0, delay * 0.25)  # full-ish jitter

    def _record_success(self, group: str) -> None:
        b = self._breakers.setdefault(group, _Breaker())
        b.failures = 0
        b.open_until = 0.0

    def _record_failure(self, group: str) -> None:
        b = self._breakers.setdefault(group, _Breaker())
        b.failures += 1
        if b.failures >= self.breaker_threshold:
            b.open_until = time.time() + self.breaker_cooldown
            log.error("ton_breaker_tripped", group=group, failures=b.failures,
                      cooldown=self.breaker_cooldown)

    # ===================================================================== #
    # Public API (same shapes as legacy tonapi.py)
    # ===================================================================== #
    async def get_wallet_info(self, address: str, user_id: Optional[int] = None) -> dict:
        """Wallet balance + whale classification. Returns {'error': ...} on
        failure (with stale data if available) — never raises to the handler."""
        cache_key = f"wallet:{address}"
        try:
            data = await self._request(f"/accounts/{quote(address, safe='')}", group="accounts", user_id=user_id)
        except TonApiError as e:
            stale = self._stale_get(cache_key)
            if stale is not None:
                log.info("ton_serving_stale", key=cache_key)
                return {**stale, "stale": True}
            return {"error": str(e)}

        balance_ton = int(data.get("balance", 0)) / 1e9
        price = await self.get_ton_price_best_effort()
        enhanced = {
            **data,
            "balance_ton": balance_ton,
            "balance_usd": balance_ton * price,
            "whale_category": self._classify_whale(balance_ton),
            "last_activity_formatted": self._fmt_ts(data.get("last_activity", 0)),
        }
        self._stale_set(cache_key, enhanced)
        return enhanced

    async def get_transactions(self, address: str, limit: int = 10, user_id: Optional[int] = None) -> dict:
        """Recent transactions, enhanced with TON amount + whale category."""
        try:
            data = await self._request(
                f"/accounts/{quote(address, safe='')}/transactions",
                group="accounts", params={"limit": limit}, user_id=user_id,
            )
        except TonApiError as e:
            return {"error": str(e), "transactions": []}

        price = await self.get_ton_price_best_effort()
        for tx in data.get("transactions", []) or []:
            amount = self._extract_tx_amount(tx)
            if amount:
                amount_ton = amount / 1e9
                tx["amount_ton"] = amount_ton
                tx["whale_category"] = self._classify_whale(amount_ton)
                tx["usd_value"] = amount_ton * price
            if "now" in tx:
                tx["timestamp_formatted"] = self._fmt_ts(tx["now"])
        return data

    async def get_jettons(self, address: str, user_id: Optional[int] = None) -> dict:
        try:
            return await self._request(
                f"/accounts/{quote(address, safe='')}/jettons", group="jettons", user_id=user_id
            )
        except TonApiError as e:
            return {"error": str(e), "balances": []}

    async def resolve_dns(self, domain: str) -> dict:
        try:
            return await self._request(f"/dns/{quote(domain, safe='')}", group="dns")
        except TonApiError as e:
            return {"error": str(e)}

    async def get_account_events(self, address: str, limit: int = 10) -> List[Dict]:
        try:
            data = await self._request(
                f"/accounts/{quote(address, safe='')}/events", group="events", params={"limit": limit}
            )
            return data.get("events", []) or []
        except TonApiError:
            return []

    async def get_large_transactions(self, limit: int = 50, min_amount: float = 1000.0) -> List[Dict]:
        """Whale movements across known whale addresses. Falls back to sample
        data (clearly marked) if the upstream is unavailable."""
        whale_addresses = self._known_whales()
        price = await self.get_ton_price_best_effort()
        results: List[Dict] = []

        # Fetch addresses concurrently (bounded by the client's connection pool).
        events_lists = await asyncio.gather(
            *[self.get_account_events(addr, limit=10) for addr in whale_addresses[:10]],
            return_exceptions=True,
        )
        for events in events_lists:
            if isinstance(events, Exception):
                continue
            for ev in events:
                amount = self._extract_event_amount(ev)
                if amount and amount >= min_amount:
                    results.append({
                        "hash": ev.get("event_id", ""),
                        "amount": amount,
                        "amount_ton": amount / 1e9,
                        "timestamp": ev.get("timestamp", 0),
                        "whale_category": self._classify_whale(amount / 1e9),
                        "usd_value": (amount / 1e9) * price,
                        "method": "whale_address_tracking",
                    })

        results.sort(key=lambda x: (x.get("timestamp", 0), x.get("amount_ton", 0)), reverse=True)
        unique, seen = [], set()
        for tx in results:
            if tx["hash"] not in seen and len(unique) < limit:
                seen.add(tx["hash"])
                unique.append(tx)
        return unique if unique else self._fallback_transactions()

    async def get_whale_alert_summary(self, hours: int = 24) -> Dict:
        cache_key = f"whale_summary:{hours}"
        try:
            txs = await self.get_large_transactions(limit=100)
            cutoff = int((datetime.now() - timedelta(hours=hours)).timestamp())
            recent = [t for t in txs if t.get("timestamp", 0) > cutoff]
            summary = {
                "period_hours": hours,
                "total_transactions": len(recent),
                "total_volume_ton": sum(t.get("amount_ton", 0) for t in recent),
                "total_usd_value": sum(t.get("usd_value", 0) for t in recent),
                "whale_breakdown": self._breakdown(recent),
                "largest_transaction": max(recent, key=lambda x: x.get("amount_ton", 0)) if recent else None,
                "most_recent": recent[0] if recent else None,
            }
            self._stale_set(cache_key, summary)
            return summary
        except Exception as e:  # noqa: BLE001
            stale = self._stale_get(cache_key)
            if stale is not None:
                return {**stale, "stale": True}
            return {"period_hours": hours, "total_transactions": 0, "error": str(e)}

    # ----- TON/USD price ------------------------------------------------- #
    async def get_ton_price_usd(self) -> float:
        """STRICT price for PAYMENTS. Returns a fresh-enough price or RAISES.

        Never returns a hardcoded value — a wrong price enables underpayment.
        A cached value younger than TON_PRICE_CACHE_TTL is acceptable.
        """
        now = time.time()
        cached = self._price_cache.get("price")
        if cached is not None and (now - self._price_cache["ts"]) < self.price_ttl:
            return cached

        client = await self._get_client()
        resp = await client.get(
            f"{self.coingecko_url}/simple/price",
            params={"ids": self.coingecko_id, "vs_currencies": "usd"},
        )
        resp.raise_for_status()
        raw = resp.json()[self.coingecko_id]["usd"]
        if not isinstance(raw, (int, float)) or raw <= 0:
            raise ValueError(f"Invalid TON price: {raw}")
        price = float(raw)

        # SEC-002: sanity-bound the price before it's used for PAYMENT validation.
        # 1) Absolute band — reject values outside a plausible TON/USD range so a
        #    glitched/manipulated feed (e.g. $0.0001 or $9999) can't poison checks.
        lo = _f("TON_PRICE_MIN_USD", 0.10)
        hi = _f("TON_PRICE_MAX_USD", 100.0)
        if not (lo <= price <= hi):
            raise ValueError(f"TON price {price} outside sane band [{lo}, {hi}] — refusing for payment use")
        # 2) Relative guard — reject a sudden >5x jump from the last good price.
        last = self._price_cache.get("price")
        if last and (price > last * 5 or price < last / 5):
            raise ValueError(f"TON price {price} deviates >5x from last {last} — refusing (possible manipulation)")

        self._price_cache = {"price": price, "ts": now}
        return price

    async def get_ton_price_best_effort(self) -> float:
        """Non-strict price for display/estimates. Returns last known or 0.0,
        never raises — safe for whale/wallet USD estimates."""
        try:
            return await self.get_ton_price_usd()
        except Exception as e:  # noqa: BLE001
            last = self._price_cache.get("price")
            if last is not None:
                return last
            log.debug("ton_price_best_effort_zero", err=str(e))
            return 0.0

    async def test_connection(self) -> Dict[str, Any]:
        """Lightweight health probe (async)."""
        try:
            await self._request("/rates", group="rates", params={"tokens": "ton", "currencies": "usd"})
            return {"api_status": "online", "auth_configured": bool(self.api_key), "fallback_available": True}
        except Exception as e:  # noqa: BLE001
            return {"api_status": "offline", "error": str(e), "fallback_available": True,
                    "auth_configured": bool(self.api_key)}

    # ----- pure helpers -------------------------------------------------- #
    def _known_whales(self) -> List[str]:
        env = os.getenv("WHALE_WATCH_ADDRESSES", "").strip()
        if env:
            return [a.strip() for a in env.split(",") if a.strip()]
        return ["EQD4FPq-PRDieyQKkizFTRtSDyucUIqrj0v_zXJmqaDp6_0t"]

    @staticmethod
    def _extract_tx_amount(tx: Dict) -> Optional[float]:
        try:
            in_msg = tx.get("in_msg", {})
            if in_msg and "value" in in_msg:
                return float(in_msg["value"])
            for msg in tx.get("out_msgs", []) or []:
                if "value" in msg:
                    return float(msg["value"])
        except (TypeError, ValueError):
            pass
        return None

    @staticmethod
    def _extract_event_amount(ev: Dict) -> Optional[float]:
        try:
            for action in ev.get("actions", []) or []:
                tt = action.get("TonTransfer") or action.get("tonTransfer")
                if tt and "amount" in tt:
                    return float(tt["amount"])
        except (TypeError, ValueError):
            pass
        return None

    def _classify_whale(self, amount_ton: float) -> str:
        t = self.whale_thresholds
        if amount_ton >= t["mega_whale"]:
            return "mega_whale"
        if amount_ton >= t["large_whale"]:
            return "large_whale"
        if amount_ton >= t["medium_whale"]:
            return "medium_whale"
        if amount_ton >= t["small_whale"]:
            return "small_whale"
        return "regular"

    @staticmethod
    def _breakdown(txs: List[Dict]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for tx in txs:
            cat = tx.get("whale_category", "unknown")
            out[cat] = out.get(cat, 0) + 1
        return out

    @staticmethod
    def _fmt_ts(ts: int) -> str:
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError):
            return "unknown"

    def _fallback_transactions(self) -> List[Dict]:
        now = int(datetime.now().timestamp())
        return [{
            "hash": "fallback_tx_1", "amount_ton": 50000, "timestamp": now - 300,
            "whale_category": "large_whale", "usd_value": 0, "method": "fallback_data",
            "note": "Upstream unavailable — sample data",
        }]


# --------------------------------------------------------------------------- #
# Singleton + lifecycle helpers for main.py
# --------------------------------------------------------------------------- #
ton_service = TonApiService()


async def startup_ton_service() -> None:
    await ton_service.startup()


async def shutdown_ton_service() -> None:
    await ton_service.aclose()


__all__ = ["TonApiService", "TonApiError", "ton_service",
           "startup_ton_service", "shutdown_ton_service"]
