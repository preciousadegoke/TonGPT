# services/ton_data_service.py
"""
TonDataService — the data layer behind the /info and /whale commands.

Goals
-----
A single, resilient, well-instrumented async service that always returns
*something useful* to the user, even when upstream APIs are flaky.

Layered strategy (best -> last resort):
    1. Redis cache            (fast path; 60s for prices, 300s for whales)
    2. TONAPI (tonapi.io)     (primary live source)
    3. CoinGecko             (fallback for TON price / market data)
    4. Stale cache           (last-known-good, served with a clear warning)
    5. Structured error      (friendly, user-facing message)

Resilience
----------
* Per-source **circuit breaker**: after N consecutive failures a source is
  "opened" for a cooldown window and skipped (fast-fail to the next layer),
  preventing thundering-herd retries against a struggling API.
* **Exponential backoff with jitter**, honouring HTTP ``Retry-After`` on 429.
* Redis is treated as best-effort: cache misses/outages never raise.
* Every method is total — it never propagates an exception to the caller.

Conventions reused from the codebase
-------------------------------------
* TONAPI base + ``TONAPI_KEY`` (Bearer) like ``services/tonapi.py``.
* ``utils.redis_conn.redis_client`` (the SafeRedisClient) for caching, called
  off the event loop via ``asyncio.to_thread`` so it never blocks.
* ``structlog`` for structured logs.

Quick self-test:
    python -m services.ton_data_service
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import structlog

logger = structlog.get_logger(__name__)

# Redis is optional. The SafeRedisClient never raises, but guard the import too.
try:
    from utils.redis_conn import redis_client as _redis
except Exception as _e:  # pragma: no cover - defensive
    _redis = None
    logger.warning("ton_data_redis_unavailable", err=str(_e))


# --------------------------------------------------------------------------- #
# Config (env-driven)
# --------------------------------------------------------------------------- #
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass
class TonDataConfig:
    tonapi_base: str = field(default_factory=lambda: os.getenv("TONAPI_BASE_URL", "https://tonapi.io/v2"))
    tonapi_key: str = field(default_factory=lambda: (os.getenv("TONAPI_KEY") or "").strip())
    coingecko_base: str = field(
        default_factory=lambda: os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3")
    )
    coingecko_ton_id: str = field(default_factory=lambda: os.getenv("COINGECKO_TON_ID", "the-open-network"))

    # Cache TTLs (seconds)
    price_ttl: int = field(default_factory=lambda: _env_int("TON_PRICE_CACHE_TTL", 60))
    whale_ttl: int = field(default_factory=lambda: _env_int("TON_WHALE_CACHE_TTL", 300))
    stale_ttl: int = field(default_factory=lambda: _env_int("TON_STALE_CACHE_TTL", 86400))

    # HTTP / retry
    http_timeout: float = field(default_factory=lambda: _env_float("TON_HTTP_TIMEOUT", 10.0))
    max_retries: int = field(default_factory=lambda: _env_int("TON_HTTP_MAX_RETRIES", 3))
    backoff_base: float = field(default_factory=lambda: _env_float("TON_HTTP_BACKOFF_BASE", 0.5))

    # Circuit breaker
    breaker_threshold: int = field(default_factory=lambda: _env_int("TON_BREAKER_THRESHOLD", 4))
    breaker_cooldown: float = field(default_factory=lambda: _env_float("TON_BREAKER_COOLDOWN", 30.0))

    # Whale tracking
    whale_min_ton: float = field(default_factory=lambda: _env_float("WHALE_MIN_TON", 10000.0))
    whale_watch_addresses: List[str] = field(default_factory=lambda: _load_watch_addresses())
    whale_max_addresses: int = field(default_factory=lambda: _env_int("WHALE_MAX_ADDRESSES", 8))

    # Optional symbol -> jetton-address map for nicer /info (e.g. {"USDT": "EQ..."}).
    known_jettons: Dict[str, str] = field(default_factory=lambda: _load_known_jettons())


def _load_watch_addresses() -> List[str]:
    raw = os.getenv("WHALE_WATCH_ADDRESSES", "").strip()
    if raw:
        return [a.strip() for a in raw.split(",") if a.strip()]
    # Sensible default: at least one high-activity address. Extend via env in prod.
    return ["EQD4FPq-PRDieyQKkizFTRtSDyucUIqrj0v_zXJmqaDp6_0t"]


def _load_known_jettons() -> Dict[str, str]:
    """Optional symbol->address map from env (JSON). Empty by default.

    Verify any addresses you add for your deployment, e.g.:
        TON_KNOWN_JETTONS='{"USDT":"EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"}'
    """
    raw = os.getenv("TON_KNOWN_JETTONS", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k).upper(): str(v) for k, v in data.items()}
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("ton_known_jettons_parse_failed", err=str(e))
        return {}


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #
@dataclass
class TokenInfo:
    symbol: str
    name: str
    address: Optional[str] = None
    price_usd: Optional[float] = None
    change_24h: Optional[float] = None       # percent
    market_cap_usd: Optional[float] = None
    volume_24h_usd: Optional[float] = None
    holders: Optional[int] = None
    verified: Optional[bool] = None
    source: str = "none"                     # tonapi | coingecko | tonapi+coingecko | stale | cache
    stale: bool = False
    cached: bool = False
    warning: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.price_usd is not None and self.error is None


@dataclass
class WhaleMovement:
    amount_ton: float
    from_address: str
    to_address: str
    category: str
    kind: str                                # "TON" or a jetton symbol
    timestamp: int
    event_id: str
    usd_value: Optional[float] = None


@dataclass
class WhaleReport:
    movements: List[WhaleMovement] = field(default_factory=list)
    source: str = "none"
    stale: bool = False
    cached: bool = False
    warning: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return bool(self.movements) and self.error is None


# --------------------------------------------------------------------------- #
# Whale size classification
# --------------------------------------------------------------------------- #
WHALE_TIERS = [
    (1_000_000, "mega_whale"),
    (100_000, "large_whale"),
    (10_000, "medium_whale"),
    (1_000, "small_whale"),
]


def classify_whale(amount_ton: float) -> str:
    for threshold, name in WHALE_TIERS:
        if amount_ton >= threshold:
            return name
    return "regular"


# --------------------------------------------------------------------------- #
# Address validation
# --------------------------------------------------------------------------- #
_USER_FRIENDLY_RE = re.compile(r"^[EU]Q[A-Za-z0-9_-]{46}$")   # EQ.../UQ..., base64url, 48 chars
_RAW_RE = re.compile(r"^-?[0-9]:[0-9a-fA-F]{64}$")            # workchain:hex, e.g. 0:abc...


def is_valid_address(value: str) -> bool:
    """True for EQ/UQ user-friendly addresses or raw ``workchain:hex`` form."""
    if not value or not isinstance(value, str):
        return False
    v = value.strip()
    return bool(_USER_FRIENDLY_RE.match(v) or _RAW_RE.match(v))


def _looks_like_address(value: str) -> bool:
    # Looser check used to route input: addresses are long; symbols are short.
    v = (value or "").strip()
    return is_valid_address(v) or (":" in v) or len(v) >= 40


# --------------------------------------------------------------------------- #
# Circuit breaker (per source/host, in-process)
# --------------------------------------------------------------------------- #
class _Breaker:
    def __init__(self, threshold: int, cooldown: float) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self._fail: Dict[str, int] = {}
        self._open_until: Dict[str, float] = {}

    def is_open(self, key: str) -> bool:
        until = self._open_until.get(key, 0.0)
        if until and time.monotonic() < until:
            return True
        return False

    def record_success(self, key: str) -> None:
        self._fail[key] = 0
        self._open_until[key] = 0.0

    def record_failure(self, key: str) -> None:
        n = self._fail.get(key, 0) + 1
        self._fail[key] = n
        if n >= self.threshold:
            self._open_until[key] = time.monotonic() + self.cooldown
            logger.warning("ton_circuit_open", source=key, failures=n, cooldown=self.cooldown)


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #
class TonDataService:
    def __init__(self, config: Optional[TonDataConfig] = None) -> None:
        self.cfg = config or TonDataConfig()
        self._session: Optional[aiohttp.ClientSession] = None
        self._breaker = _Breaker(self.cfg.breaker_threshold, self.cfg.breaker_cooldown)

    # ---- lifecycle -------------------------------------------------------- #
    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.cfg.http_timeout),
                headers={"User-Agent": "TonGPT-Bot/1.0", "Accept": "application/json"},
            )
        return self._session

    async def aclose(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ---- redis cache (best-effort, off the event loop) -------------------- #
    async def _cache_get(self, key: str) -> Optional[dict]:
        if not _redis:
            return None
        try:
            raw = await asyncio.to_thread(_redis.get, key)
            return json.loads(raw) if raw else None
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("ton_cache_get_failed", key=key, err=str(e))
            return None

    async def _cache_set(self, key: str, value: dict, ttl: int) -> None:
        if not _redis:
            return
        try:
            await asyncio.to_thread(_redis.set, key, json.dumps(value), ttl)
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("ton_cache_set_failed", key=key, err=str(e))

    async def _store_good(self, fresh_key: str, stale_key: str, value: dict, ttl: int) -> None:
        # Write both the short-TTL fresh entry and the long-TTL last-known-good.
        await self._cache_set(fresh_key, value, ttl)
        await self._cache_set(stale_key, value, self.cfg.stale_ttl)

    # ---- HTTP with breaker + backoff -------------------------------------- #
    async def _get_json(
        self, source: str, url: str, params: Optional[dict] = None, auth: bool = False
    ) -> Tuple[Optional[Any], Optional[str]]:
        """GET JSON with circuit-breaker + exponential backoff.

        Returns ``(data, None)`` on success or ``(None, error_code)`` on failure.
        Never raises.
        """
        if self._breaker.is_open(source):
            logger.info("ton_circuit_skip", source=source)
            return None, "circuit_open"

        headers = {}
        if auth and self.cfg.tonapi_key:
            headers["Authorization"] = f"Bearer {self.cfg.tonapi_key}"

        session = await self._session_get()
        last_err = "unknown"

        for attempt in range(self.cfg.max_retries + 1):
            try:
                async with session.get(url, params=params, headers=headers) as resp:
                    if resp.status == 200:
                        self._breaker.record_success(source)
                        return await resp.json(), None

                    # Rate limited: honour Retry-After, then back off.
                    if resp.status == 429:
                        retry_after = resp.headers.get("Retry-After")
                        delay = self._delay(attempt, retry_after)
                        logger.warning("ton_rate_limited", source=source, attempt=attempt, delay=round(delay, 2))
                        last_err = "rate_limited"
                        if attempt < self.cfg.max_retries:
                            await asyncio.sleep(delay)
                            continue
                        break

                    # Transient server errors -> retry.
                    if 500 <= resp.status < 600:
                        last_err = f"http_{resp.status}"
                        if attempt < self.cfg.max_retries:
                            await asyncio.sleep(self._delay(attempt))
                            continue
                        break

                    # Other 4xx -> not retryable.
                    logger.warning("ton_http_error", source=source, status=resp.status, url=url)
                    self._breaker.record_failure(source)
                    return None, f"http_{resp.status}"

            except asyncio.TimeoutError:
                last_err = "timeout"
            except aiohttp.ClientError as e:
                last_err = f"client_error:{type(e).__name__}"
            except Exception as e:  # pragma: no cover - last resort
                last_err = f"unexpected:{type(e).__name__}"
                logger.error("ton_http_unexpected", source=source, err=str(e))

            if attempt < self.cfg.max_retries:
                await asyncio.sleep(self._delay(attempt))

        self._breaker.record_failure(source)
        logger.warning("ton_request_failed", source=source, url=url, error=last_err)
        return None, last_err

    def _delay(self, attempt: int, retry_after: Optional[str] = None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), 30.0)
            except (TypeError, ValueError):
                pass
        # Exponential backoff with full jitter.
        return self.cfg.backoff_base * (2 ** attempt) + random.uniform(0, self.cfg.backoff_base)

    # ===================================================================== #
    # TON price (TONAPI primary, CoinGecko fallback) — used by info + whales
    # ===================================================================== #
    async def get_ton_price(self) -> Tuple[Optional[float], Optional[float], str]:
        """Return ``(price_usd, change_24h_pct, source)``. Cached for ``price_ttl``."""
        cached = await self._cache_get("ton:price")
        if cached:
            return cached.get("price"), cached.get("change_24h"), "cache"

        # Primary: TONAPI rates
        data, err = await self._get_json(
            "tonapi", f"{self.cfg.tonapi_base}/rates",
            params={"tokens": "ton", "currencies": "usd"}, auth=True,
        )
        price, change = self._parse_tonapi_rate(data)
        source = "tonapi"

        # Fallback: CoinGecko
        if price is None:
            cg, _ = await self._get_json(
                "coingecko", f"{self.cfg.coingecko_base}/simple/price",
                params={
                    "ids": self.cfg.coingecko_ton_id, "vs_currencies": "usd",
                    "include_24hr_change": "true",
                },
            )
            price, change = self._parse_coingecko_simple(cg)
            source = "coingecko"

        if price is not None:
            payload = {"price": price, "change_24h": change}
            await self._store_good("ton:price", "ton:price:last", payload, self.cfg.price_ttl)
            return price, change, source

        # Last resort: stale
        stale = await self._cache_get("ton:price:last")
        if stale:
            return stale.get("price"), stale.get("change_24h"), "stale"
        return None, None, "none"

    @staticmethod
    def _parse_tonapi_rate(data: Any) -> Tuple[Optional[float], Optional[float]]:
        """TONAPI /rates -> (price_usd, change_24h_pct). Robust to token-key casing."""
        try:
            rates = (data or {}).get("rates") or {}
            if not rates:
                return None, None
            entry = next(iter(rates.values()))           # first token in the map
            price = entry.get("prices", {}).get("USD")
            diff = entry.get("diff_24h", {}).get("USD")  # e.g. "+1.95%" (unicode minus possible)
            change = None
            if isinstance(diff, str):
                cleaned = diff.replace("%", "").replace("−", "-").replace(" ", "")
                try:
                    change = float(cleaned)
                except ValueError:
                    change = None
            return (float(price) if price is not None else None), change
        except Exception:
            return None, None

    @staticmethod
    def _parse_coingecko_simple(data: Any) -> Tuple[Optional[float], Optional[float]]:
        try:
            entry = next(iter((data or {}).values()))
            price = entry.get("usd")
            change = entry.get("usd_24h_change")
            return (
                float(price) if price is not None else None,
                float(change) if change is not None else None,
            )
        except Exception:
            return None, None

    # ===================================================================== #
    # get_token_info
    # ===================================================================== #
    async def get_token_info(self, address_or_symbol: str) -> TokenInfo:
        """Resolve a token by symbol (TON or a known jetton) or by jetton address."""
        query = (address_or_symbol or "").strip()
        if not query:
            return TokenInfo(symbol="?", name="Unknown", error="empty_query",
                             warning="Please provide a token symbol or address.")

        symbol_upper = query.upper()

        # Route: native TON vs jetton symbol-map vs raw address.
        if symbol_upper in ("TON", "TONCOIN"):
            return await self._token_info_ton()
        if symbol_upper in self.cfg.known_jettons:
            return await self._token_info_jetton(self.cfg.known_jettons[symbol_upper], symbol_hint=symbol_upper)
        if _looks_like_address(query):
            if not is_valid_address(query):
                return TokenInfo(symbol="?", name="Unknown", address=query, error="invalid_address",
                                 warning="That doesn't look like a valid TON address (EQ.../UQ... or raw 0:hex).")
            return await self._token_info_jetton(query)

        return TokenInfo(
            symbol=symbol_upper, name=symbol_upper, error="unknown_symbol",
            warning=(f"I don't know the address for '{query}'. Send the jetton address "
                     f"(EQ.../UQ...), or use /info TON."),
        )

    async def _token_info_ton(self) -> TokenInfo:
        cache_key, stale_key = "ton:info:TON", "ton:info:TON:last"
        cached = await self._cache_get(cache_key)
        if cached:
            return TokenInfo(**{**cached, "cached": True, "source": "cache"})

        price, change, price_src = await self.get_ton_price()

        # Enrich with market cap + volume from CoinGecko (TONAPI rates lacks these).
        mcap = vol = None
        cg, _ = await self._get_json(
            "coingecko", f"{self.cfg.coingecko_base}/simple/price",
            params={
                "ids": self.cfg.coingecko_ton_id, "vs_currencies": "usd",
                "include_market_cap": "true", "include_24hr_vol": "true",
                "include_24hr_change": "true",
            },
        )
        try:
            entry = next(iter((cg or {}).values()))
            mcap = entry.get("usd_market_cap")
            vol = entry.get("usd_24h_vol")
            if change is None:
                change = entry.get("usd_24h_change")
            if price is None and entry.get("usd") is not None:
                price, price_src = float(entry["usd"]), "coingecko"
        except Exception:
            pass

        if price is None:
            stale = await self._cache_get(stale_key)
            if stale:
                return TokenInfo(**{**stale, "stale": True, "source": "stale",
                                    "warning": "⚠️ Live data unavailable — showing last known values."})
            return TokenInfo(symbol="TON", name="Toncoin", error="sources_unavailable",
                             warning="⚠️ TON price is temporarily unavailable. Please try again shortly.")

        info = TokenInfo(
            symbol="TON", name="Toncoin", address=None,
            price_usd=price, change_24h=change,
            market_cap_usd=float(mcap) if mcap is not None else None,
            volume_24h_usd=float(vol) if vol is not None else None,
            source=("tonapi+coingecko" if price_src == "tonapi" else price_src),
        )
        await self._store_good(cache_key, stale_key, _info_payload(info), self.cfg.price_ttl)
        return info

    async def _token_info_jetton(self, address: str, symbol_hint: Optional[str] = None) -> TokenInfo:
        cache_key, stale_key = f"ton:info:{address}", f"ton:info:{address}:last"
        cached = await self._cache_get(cache_key)
        if cached:
            return TokenInfo(**{**cached, "cached": True, "source": "cache"})

        # Metadata from TONAPI jettons endpoint.
        meta, meta_err = await self._get_json(
            "tonapi", f"{self.cfg.tonapi_base}/jettons/{address}", auth=True
        )
        # Price from TONAPI rates (jettons keyed by address).
        rate, _ = await self._get_json(
            "tonapi", f"{self.cfg.tonapi_base}/rates",
            params={"tokens": address, "currencies": "usd"}, auth=True,
        )
        price, change = self._parse_tonapi_rate(rate)

        name = symbol = None
        holders = None
        verified = None
        if meta:
            md = meta.get("metadata", {}) or {}
            name = md.get("name")
            symbol = md.get("symbol")
            holders = meta.get("holders_count")
            verified = (meta.get("verification") == "whitelist") if meta.get("verification") else None

        if not name and not price:
            stale = await self._cache_get(stale_key)
            if stale:
                return TokenInfo(**{**stale, "stale": True, "source": "stale",
                                    "warning": "⚠️ Live data unavailable — showing last known values."})
            return TokenInfo(
                symbol=symbol_hint or "?", name="Unknown jetton", address=address,
                error=meta_err or "not_found",
                warning="⚠️ Couldn't fetch this jetton right now. Double-check the address and try again.",
            )

        info = TokenInfo(
            symbol=symbol or symbol_hint or "?",
            name=name or "Unknown jetton",
            address=address,
            price_usd=price,
            change_24h=change,
            holders=holders,
            verified=verified,
            source="tonapi",
        )
        await self._store_good(cache_key, stale_key, _info_payload(info), self.cfg.price_ttl)
        return info

    # ===================================================================== #
    # get_whale_movements
    # ===================================================================== #
    async def get_whale_movements(self, limit: int = 5) -> WhaleReport:
        limit = max(1, min(int(limit or 5), 50))
        cache_key, stale_key = f"ton:whale:{self.cfg.whale_min_ton}", "ton:whale:last"

        cached = await self._cache_get(cache_key)
        if cached:
            return _whale_report_from_payload(cached, cached=True, source="cache", limit=limit)

        ton_price, _, _ = await self.get_ton_price()
        addresses = self.cfg.whale_watch_addresses[: self.cfg.whale_max_addresses]

        movements: List[WhaleMovement] = []
        any_success = False
        for addr in addresses:
            data, err = await self._get_json(
                "tonapi", f"{self.cfg.tonapi_base}/accounts/{addr}/events",
                params={"limit": 20}, auth=True,
            )
            if data is None:
                continue
            any_success = True
            movements.extend(self._extract_movements(data, ton_price))

        if not any_success:
            stale = await self._cache_get(stale_key)
            if stale:
                rep = _whale_report_from_payload(stale, cached=False, source="stale", limit=limit)
                rep.stale = True
                rep.warning = "⚠️ Live whale data unavailable — showing the last known movements."
                return rep
            return WhaleReport(
                source="none", error="sources_unavailable",
                warning="⚠️ Whale tracking is temporarily unavailable. Please try again shortly.",
            )

        # Sort newest + largest first, dedupe by event id.
        movements.sort(key=lambda m: (m.timestamp, m.amount_ton), reverse=True)
        seen, unique = set(), []
        for m in movements:
            if m.event_id in seen:
                continue
            seen.add(m.event_id)
            unique.append(m)

        report = WhaleReport(movements=unique[:limit], source="tonapi")
        if not report.movements:
            report.warning = "No whale-sized movements found right now. Check back soon."
        await self._store_good(cache_key, stale_key, _whale_payload(unique[:limit]), self.cfg.whale_ttl)
        return report

    def _extract_movements(self, data: dict, ton_price: Optional[float]) -> List[WhaleMovement]:
        out: List[WhaleMovement] = []
        for event in (data.get("events") or []):
            event_id = event.get("event_id") or event.get("lt") or ""
            ts = int(event.get("timestamp") or 0)
            for action in (event.get("actions") or []):
                atype = action.get("type")
                if atype == "TonTransfer":
                    body = action.get("TonTransfer", {}) or {}
                    amount_ton = float(body.get("amount", 0) or 0) / 1e9
                    if amount_ton < self.cfg.whale_min_ton:
                        continue
                    out.append(WhaleMovement(
                        amount_ton=amount_ton,
                        from_address=_addr_of(body.get("sender")),
                        to_address=_addr_of(body.get("recipient")),
                        category=classify_whale(amount_ton),
                        kind="TON",
                        timestamp=ts,
                        event_id=f"{event_id}:{len(out)}",
                        usd_value=(amount_ton * ton_price) if ton_price else None,
                    ))
        return out


# --------------------------------------------------------------------------- #
# (de)serialization helpers for the cache
# --------------------------------------------------------------------------- #
def _info_payload(info: TokenInfo) -> dict:
    d = asdict(info)
    # Don't persist transient flags.
    for k in ("cached", "stale", "warning", "error"):
        d.pop(k, None)
    return d


def _whale_payload(movements: List[WhaleMovement]) -> dict:
    return {"movements": [asdict(m) for m in movements]}


def _whale_report_from_payload(payload: dict, *, cached: bool, source: str, limit: int) -> WhaleReport:
    movements = [WhaleMovement(**m) for m in (payload.get("movements") or [])][:limit]
    return WhaleReport(movements=movements, source=source, cached=cached)


def _addr_of(party: Any) -> str:
    if isinstance(party, dict):
        return party.get("address") or party.get("name") or "unknown"
    return "unknown"


# --------------------------------------------------------------------------- #
# Module singleton + convenience wrappers (what handlers import)
# --------------------------------------------------------------------------- #
_service: Optional[TonDataService] = None


def get_ton_data_service() -> TonDataService:
    global _service
    if _service is None:
        _service = TonDataService()
    return _service


async def get_token_info(address_or_symbol: str) -> TokenInfo:
    return await get_ton_data_service().get_token_info(address_or_symbol)


async def get_whale_movements(limit: int = 5) -> WhaleReport:
    return await get_ton_data_service().get_whale_movements(limit)


__all__ = [
    "TonDataService",
    "TonDataConfig",
    "TokenInfo",
    "WhaleMovement",
    "WhaleReport",
    "is_valid_address",
    "classify_whale",
    "get_ton_data_service",
    "get_token_info",
    "get_whale_movements",
]


# --------------------------------------------------------------------------- #
# Self-test:  python -m services.ton_data_service
# Hits live TONAPI/CoinGecko (no key needed for basic calls). Redis optional.
# --------------------------------------------------------------------------- #
async def _selftest() -> None:
    svc = TonDataService()
    try:
        print("address validation:")
        for a in ["EQD4FPq-PRDieyQKkizFTRtSDyucUIqrj0v_zXJmqaDp6_0t", "0:" + "a" * 64, "TON", "notanaddr"]:
            print(f"  {a[:24]:24} -> valid={is_valid_address(a)}")

        info = await svc.get_token_info("TON")
        print(f"\n/info TON -> ok={info.ok} source={info.source} "
              f"price=${info.price_usd} change={info.change_24h}% mcap={info.market_cap_usd}")

        report = await svc.get_whale_movements(limit=3)
        print(f"\n/whale -> ok={report.ok} source={report.source} "
              f"count={len(report.movements)} warning={report.warning}")
        for m in report.movements:
            print(f"  {m.amount_ton:,.0f} TON ({m.category}) {m.from_address[:10]}.. -> {m.to_address[:10]}..")
    finally:
        await svc.aclose()


if __name__ == "__main__":
    asyncio.run(_selftest())
