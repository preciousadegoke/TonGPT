# services/dexscreener_service.py
"""
DexScreenerService — rich market data for the /info and /trending commands.

Strategy
--------
    1. Redis cache              (fast path; 45s token info, 60s trending)
    2. DexScreener public API   (primary; price, perf, liquidity, FDV, volume)
    3. TONAPI holders           (enrichment: top-holder concentration)
    4. ton_data_service         (fallback: native TON + TONAPI/CoinGecko)
    5. Stale cache              (last-known-good, served with a warning)
    6. Structured error         (friendly, user-facing message)

DexScreener has no auth and is generous (~300 req/min on these endpoints), but
we still cache aggressively and degrade gracefully so the bot stays fast and
never hard-fails.

Trustworthiness note
--------------------
DexScreener does not expose honeypot detection, LP-lock status, or holder lists.
The safety signals here are **heuristics** derived from real on-chain market data
(liquidity, FDV, pair age, buy/sell flow) plus top-holder concentration fetched
from TONAPI. They are clearly labelled as signals — not guarantees — so users get
useful warnings without false certainty.

Self-test:
    python -m services.dexscreener_service
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import aiohttp
import structlog

logger = structlog.get_logger(__name__)

# Reuse the existing data layer for native-TON and as a last-resort fallback.
try:
    from services.ton_data_service import get_ton_data_service
except Exception as _e:  # pragma: no cover - defensive
    get_ton_data_service = None
    logger.warning("dex_ton_data_unavailable", err=str(_e))

# Optional Redis (SafeRedisClient never raises).
try:
    from utils.redis_conn import redis_client as _redis
except Exception as _e:  # pragma: no cover - defensive
    _redis = None
    logger.warning("dex_redis_unavailable", err=str(_e))


# --------------------------------------------------------------------------- #
# Config
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


# Default curated TON jettons for /trending (verified addresses). Extend in prod
# via TON_TRENDING_TOKENS (comma-separated addresses).
_DEFAULT_TRENDING = [
    "EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT",   # Notcoin (NOT)
    "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs",   # Tether USD (USDT)
    "EQATcUc69sGSCCMSadsVUKdGwM1BMKS-HKCWGPk60xZGgwsK",   # TON Fish (FISH)
    "EQCFVNlRb-NHHDQfv3Q9xvDXBLJlay855_xREsq5ZDX6KN-w",   # MyTonWallet Coin (MY)
]


@dataclass
class DexConfig:
    dex_base: str = field(default_factory=lambda: os.getenv("DEXSCREENER_BASE_URL", "https://api.dexscreener.com"))
    chain: str = field(default_factory=lambda: os.getenv("DEXSCREENER_CHAIN", "ton"))
    tonapi_base: str = field(default_factory=lambda: os.getenv("TONAPI_BASE_URL", "https://tonapi.io/v2"))
    tonapi_key: str = field(default_factory=lambda: (os.getenv("TONAPI_KEY") or "").strip())

    info_ttl: int = field(default_factory=lambda: _env_int("DEX_INFO_CACHE_TTL", 45))
    trending_ttl: int = field(default_factory=lambda: _env_int("DEX_TRENDING_CACHE_TTL", 60))
    stale_ttl: int = field(default_factory=lambda: _env_int("DEX_STALE_CACHE_TTL", 86400))

    http_timeout: float = field(default_factory=lambda: _env_float("DEX_HTTP_TIMEOUT", 10.0))
    max_retries: int = field(default_factory=lambda: _env_int("DEX_HTTP_MAX_RETRIES", 2))
    backoff_base: float = field(default_factory=lambda: _env_float("DEX_HTTP_BACKOFF_BASE", 0.5))
    breaker_threshold: int = field(default_factory=lambda: _env_int("DEX_BREAKER_THRESHOLD", 4))
    breaker_cooldown: float = field(default_factory=lambda: _env_float("DEX_BREAKER_COOLDOWN", 30.0))

    # Safety thresholds (heuristics)
    liq_very_low_usd: float = field(default_factory=lambda: _env_float("DEX_LIQ_VERY_LOW_USD", 5000.0))
    liq_low_usd: float = field(default_factory=lambda: _env_float("DEX_LIQ_LOW_USD", 25000.0))
    holder_warn_pct: float = field(default_factory=lambda: _env_float("DEX_HOLDER_WARN_PCT", 20.0))
    holder_danger_pct: float = field(default_factory=lambda: _env_float("DEX_HOLDER_DANGER_PCT", 50.0))

    trending_tokens: List[str] = field(default_factory=lambda: _load_trending_tokens())
    trending_search: str = field(default_factory=lambda: os.getenv("DEX_TRENDING_SEARCH", "ton"))


def _load_trending_tokens() -> List[str]:
    raw = os.getenv("TON_TRENDING_TOKENS", "").strip()
    if raw:
        return [a.strip() for a in raw.split(",") if a.strip()]
    return list(_DEFAULT_TRENDING)


# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #
@dataclass
class SafetyReport:
    risk_level: str = "unknown"              # low | medium | high | unknown
    flags: List[str] = field(default_factory=list)
    top_holder_pct: Optional[float] = None
    liquidity_locked: Optional[bool] = None  # None = not verifiable from public APIs
    honeypot_suspected: Optional[bool] = None


@dataclass
class TokenMarket:
    symbol: str
    name: str
    address: Optional[str] = None
    price_usd: Optional[float] = None
    change_5m: Optional[float] = None
    change_1h: Optional[float] = None
    change_6h: Optional[float] = None
    change_24h: Optional[float] = None
    liquidity_usd: Optional[float] = None
    fdv: Optional[float] = None
    market_cap: Optional[float] = None
    volume_24h: Optional[float] = None
    buys_24h: Optional[int] = None
    sells_24h: Optional[int] = None
    dex: Optional[str] = None
    pair_address: Optional[str] = None
    chart_url: Optional[str] = None
    tonviewer_url: Optional[str] = None
    image_url: Optional[str] = None
    pair_created_at: Optional[int] = None    # ms
    safety: SafetyReport = field(default_factory=SafetyReport)
    source: str = "none"                     # dexscreener | ton_data | cache | stale
    cached: bool = False
    stale: bool = False
    warning: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.price_usd is not None and self.error is None


@dataclass
class TrendingToken:
    rank: int
    symbol: str
    name: str
    address: str
    price_usd: Optional[float]
    change_24h: Optional[float]
    volume_24h: Optional[float]
    liquidity_usd: Optional[float]
    pair_url: Optional[str]


@dataclass
class TrendingReport:
    tokens: List[TrendingToken] = field(default_factory=list)
    sort_by: str = "volume"
    source: str = "none"
    cached: bool = False
    stale: bool = False
    warning: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return bool(self.tokens) and self.error is None


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _f(x: Any) -> Optional[float]:
    """Lenient float parse (DexScreener returns numbers AND numeric strings)."""
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


_RISK_ORDER = {"unknown": 0, "low": 1, "medium": 2, "high": 3}


def _escalate(current: str, new: str) -> str:
    return new if _RISK_ORDER.get(new, 0) > _RISK_ORDER.get(current, 0) else current


def _looks_like_address(value: str) -> bool:
    v = (value or "").strip()
    return (v.startswith(("EQ", "UQ")) and len(v) == 48) or (":" in v and len(v) > 40)


# --------------------------------------------------------------------------- #
# Circuit breaker (per host)
# --------------------------------------------------------------------------- #
class _Breaker:
    def __init__(self, threshold: int, cooldown: float) -> None:
        self.threshold, self.cooldown = threshold, cooldown
        self._fail: Dict[str, int] = {}
        self._open_until: Dict[str, float] = {}

    def is_open(self, key: str) -> bool:
        return time.monotonic() < self._open_until.get(key, 0.0)

    def ok(self, key: str) -> None:
        self._fail[key] = 0
        self._open_until[key] = 0.0

    def fail(self, key: str) -> None:
        n = self._fail.get(key, 0) + 1
        self._fail[key] = n
        if n >= self.threshold:
            self._open_until[key] = time.monotonic() + self.cooldown
            logger.warning("dex_circuit_open", source=key, failures=n)


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #
class DexScreenerService:
    def __init__(self, config: Optional[DexConfig] = None) -> None:
        self.cfg = config or DexConfig()
        self._session: Optional[aiohttp.ClientSession] = None
        self._breaker = _Breaker(self.cfg.breaker_threshold, self.cfg.breaker_cooldown)

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
        # Also close the fallback data-layer session if we used it.
        if get_ton_data_service is not None:
            try:
                await get_ton_data_service().aclose()
            except Exception:  # pragma: no cover
                pass

    # ---- cache (best-effort, off the loop) -------------------------------- #
    async def _cache_get(self, key: str) -> Optional[dict]:
        if not _redis:
            return None
        try:
            raw = await asyncio.to_thread(_redis.get, key)
            return json.loads(raw) if raw else None
        except Exception as e:  # pragma: no cover
            logger.debug("dex_cache_get_failed", key=key, err=str(e))
            return None

    async def _cache_set(self, key: str, value: dict, ttl: int) -> None:
        if not _redis:
            return
        try:
            await asyncio.to_thread(_redis.set, key, json.dumps(value), ttl)
        except Exception as e:  # pragma: no cover
            logger.debug("dex_cache_set_failed", key=key, err=str(e))

    async def _store_good(self, fresh_key: str, stale_key: str, value: dict, ttl: int) -> None:
        await self._cache_set(fresh_key, value, ttl)
        await self._cache_set(stale_key, value, self.cfg.stale_ttl)

    # ---- HTTP with breaker + backoff -------------------------------------- #
    async def _get(self, source: str, url: str, auth: bool = False) -> Tuple[Optional[Any], Optional[str]]:
        if self._breaker.is_open(source):
            return None, "circuit_open"

        headers = {}
        if auth and self.cfg.tonapi_key:
            headers["Authorization"] = f"Bearer {self.cfg.tonapi_key}"

        session = await self._session_get()
        last_err = "unknown"
        for attempt in range(self.cfg.max_retries + 1):
            try:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        self._breaker.ok(source)
                        return await resp.json(), None
                    if resp.status == 429:
                        delay = self._delay(attempt, resp.headers.get("Retry-After"))
                        logger.warning("dex_rate_limited", source=source, delay=round(delay, 2))
                        last_err = "rate_limited"
                        if attempt < self.cfg.max_retries:
                            await asyncio.sleep(delay)
                            continue
                        break
                    if 500 <= resp.status < 600:
                        last_err = f"http_{resp.status}"
                        if attempt < self.cfg.max_retries:
                            await asyncio.sleep(self._delay(attempt))
                            continue
                        break
                    self._breaker.fail(source)
                    return None, f"http_{resp.status}"
            except asyncio.TimeoutError:
                last_err = "timeout"
            except aiohttp.ClientError as e:
                last_err = f"client_error:{type(e).__name__}"
            except Exception as e:  # pragma: no cover
                last_err = f"unexpected:{type(e).__name__}"
            if attempt < self.cfg.max_retries:
                await asyncio.sleep(self._delay(attempt))

        self._breaker.fail(source)
        logger.warning("dex_request_failed", source=source, url=url, error=last_err)
        return None, last_err

    def _delay(self, attempt: int, retry_after: Optional[str] = None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), 30.0)
            except (TypeError, ValueError):
                pass
        return self.cfg.backoff_base * (2 ** attempt) + random.uniform(0, self.cfg.backoff_base)

    # ===================================================================== #
    # Pair helpers
    # ===================================================================== #
    def _ton_pairs(self, payload: Any) -> List[dict]:
        pairs = (payload or {}).get("pairs") if isinstance(payload, dict) else payload
        pairs = pairs or []
        return [p for p in pairs if (p.get("chainId") == self.cfg.chain)]

    @staticmethod
    def _liq(p: dict) -> float:
        return _f((p.get("liquidity") or {}).get("usd")) or 0.0

    def _best_pair(self, pairs: List[dict]) -> Optional[dict]:
        """Most liquid pair = the canonical market for a token."""
        return max(pairs, key=self._liq) if pairs else None

    def _tonviewer(self, address: Optional[str]) -> Optional[str]:
        return f"https://tonviewer.com/{address}" if address else None

    def _pair_to_market(self, p: dict) -> TokenMarket:
        base = p.get("baseToken", {}) or {}
        pc = p.get("priceChange", {}) or {}
        vol = p.get("volume", {}) or {}
        txns24 = (p.get("txns", {}) or {}).get("h24", {}) or {}
        addr = base.get("address")
        return TokenMarket(
            symbol=base.get("symbol") or "?",
            name=base.get("name") or "Unknown",
            address=addr,
            price_usd=_f(p.get("priceUsd")),
            change_5m=_f(pc.get("m5")),
            change_1h=_f(pc.get("h1")),
            change_6h=_f(pc.get("h6")),
            change_24h=_f(pc.get("h24")),
            liquidity_usd=_f((p.get("liquidity") or {}).get("usd")),
            fdv=_f(p.get("fdv")),
            market_cap=_f(p.get("marketCap")),
            volume_24h=_f(vol.get("h24")),
            buys_24h=txns24.get("buys"),
            sells_24h=txns24.get("sells"),
            dex=p.get("dexId"),
            pair_address=p.get("pairAddress"),
            chart_url=p.get("url") or (f"https://dexscreener.com/{self.cfg.chain}/{p.get('pairAddress')}"),
            tonviewer_url=self._tonviewer(addr),
            image_url=(p.get("info", {}) or {}).get("imageUrl"),
            pair_created_at=p.get("pairCreatedAt"),
            source="dexscreener",
        )

    # ===================================================================== #
    # Safety signals
    # ===================================================================== #
    async def _safety(self, p: dict, address: Optional[str]) -> SafetyReport:
        flags: List[str] = []
        risk = "low"

        liq = self._liq(p)
        fdv = _f(p.get("fdv")) or 0.0
        created = p.get("pairCreatedAt")
        txns24 = (p.get("txns", {}) or {}).get("h24", {}) or {}
        buys = int(txns24.get("buys") or 0)
        sells = int(txns24.get("sells") or 0)

        # Liquidity depth
        if liq < self.cfg.liq_very_low_usd:
            flags.append(f"🟥 Very low liquidity (${liq:,.0f})")
            risk = _escalate(risk, "high")
        elif liq < self.cfg.liq_low_usd:
            flags.append(f"🟧 Low liquidity (${liq:,.0f})")
            risk = _escalate(risk, "medium")

        # Liquidity vs valuation
        if fdv > 0 and liq > 0 and (liq / fdv) < 0.01:
            flags.append("🟧 Liquidity is tiny vs FDV — hard to exit")
            risk = _escalate(risk, "medium")

        # Pair age
        if created:
            age_h = max(0.0, (time.time() - (created / 1000.0)) / 3600.0)
            if age_h < 24:
                flags.append(f"🟧 New pair ({age_h:.0f}h old) — higher risk")
                risk = _escalate(risk, "medium")

        # Honeypot heuristic: real buy flow but no sells at all.
        honeypot = None
        if buys >= 5 and sells == 0:
            honeypot = True
            flags.append("🟥 No sells in 24h — possible honeypot")
            risk = _escalate(risk, "high")

        # Top-holder concentration (TONAPI enrichment)
        top_pct = await self._top_holder_pct(address) if address else None
        if top_pct is not None:
            if top_pct >= self.cfg.holder_danger_pct:
                flags.append(f"🟥 Top holder controls {top_pct:.0f}% of supply")
                risk = _escalate(risk, "high")
            elif top_pct >= self.cfg.holder_warn_pct:
                flags.append(f"🟧 Top holder controls {top_pct:.0f}% of supply")
                risk = _escalate(risk, "medium")

        if not flags:
            flags.append("🟩 No major risk signals detected")

        return SafetyReport(
            risk_level=risk,
            flags=flags,
            top_holder_pct=round(top_pct, 1) if top_pct is not None else None,
            liquidity_locked=None,  # not verifiable from public APIs — stay honest
            honeypot_suspected=honeypot,
        )

    async def _top_holder_pct(self, address: str) -> Optional[float]:
        """Largest single holder as % of supply, via TONAPI. Best-effort."""
        meta, _ = await self._get("tonapi", f"{self.cfg.tonapi_base}/jettons/{address}", auth=True)
        holders, _ = await self._get(
            "tonapi", f"{self.cfg.tonapi_base}/jettons/{address}/holders?limit=1", auth=True
        )
        try:
            total = float((meta or {}).get("total_supply") or 0)
            top = float(((holders or {}).get("addresses") or [{}])[0].get("balance") or 0)
            if total > 0 and top > 0:
                return min(100.0, top / total * 100.0)
        except Exception:
            return None
        return None

    # ===================================================================== #
    # get_token_info
    # ===================================================================== #
    async def get_token_info(self, query: str) -> TokenMarket:
        q = (query or "").strip()
        if not q:
            return TokenMarket(symbol="?", name="Unknown", error="empty_query",
                               warning="Send a token symbol, name, or address.")

        # Native TON is best served by the existing data layer.
        if q.upper() in ("TON", "TONCOIN"):
            return await self._from_ton_data("TON")

        key = f"dex:info:{q.lower()}"
        stale_key = f"{key}:last"
        cached = await self._cache_get(key)
        if cached:
            return _market_from_payload(cached, cached=True, source="cache")

        # Resolve query -> TON pairs.
        if _looks_like_address(q):
            payload, err = await self._get("dexscreener", f"{self.cfg.dex_base}/latest/dex/tokens/{q}")
        else:
            payload, err = await self._get(
                "dexscreener", f"{self.cfg.dex_base}/latest/dex/search?q={quote(q, safe='')}"
            )
        pairs = self._ton_pairs(payload)
        best = self._best_pair(pairs)

        if best is None:
            # Fallback to TONAPI/CoinGecko via ton_data_service (handles addresses).
            fb = await self._from_ton_data(q)
            if fb.ok:
                return fb
            stale = await self._cache_get(stale_key)
            if stale:
                m = _market_from_payload(stale, cached=False, source="stale")
                m.stale = True
                m.warning = "⚠️ Live data unavailable — showing last known values."
                return m
            return TokenMarket(symbol=q.upper(), name="Unknown", error=err or "not_found",
                               warning="🚫 No TON market found for that token. Check the symbol/address.")

        market = self._pair_to_market(best)
        market.safety = await self._safety(best, market.address)
        await self._store_good(key, stale_key, _market_to_payload(market), self.cfg.info_ttl)
        return market

    async def _from_ton_data(self, query: str) -> TokenMarket:
        """Adapter: ton_data_service.TokenInfo -> TokenMarket."""
        if get_ton_data_service is None:
            return TokenMarket(symbol=query.upper(), name="Unknown", error="no_fallback")
        try:
            info = await get_ton_data_service().get_token_info(query)
        except Exception as e:
            logger.error("dex_fallback_failed", err=str(e))
            return TokenMarket(symbol=query.upper(), name="Unknown", error="fallback_error")
        return TokenMarket(
            symbol=info.symbol, name=info.name, address=info.address,
            price_usd=info.price_usd, change_24h=info.change_24h,
            market_cap=info.market_cap_usd, volume_24h=info.volume_24h_usd,
            tonviewer_url=self._tonviewer(info.address),
            source="ton_data", stale=info.stale, warning=info.warning, error=info.error,
        )

    # ===================================================================== #
    # get_trending
    # ===================================================================== #
    async def get_trending(self, sort_by: str = "volume", limit: int = 10) -> TrendingReport:
        sort_by = "age" if str(sort_by).lower() in ("age", "new", "newest") else "volume"
        limit = max(1, min(int(limit or 10), 25))
        key = f"dex:trending:{sort_by}:{limit}"
        stale_key = f"dex:trending:{sort_by}:last"

        cached = await self._cache_get(key)
        if cached:
            return _trending_from_payload(cached, cached=True, source="cache", limit=limit)

        pairs: List[dict] = []
        any_ok = False

        # (a) Curated majors in a single multi-address call.
        if self.cfg.trending_tokens:
            addrs = ",".join(self.cfg.trending_tokens[:30])
            payload, _ = await self._get("dexscreener", f"{self.cfg.dex_base}/latest/dex/tokens/{addrs}")
            tp = self._ton_pairs(payload)
            if tp:
                any_ok = True
                pairs.extend(tp)

        # (b) Discovery via chain-filtered search.
        if self.cfg.trending_search:
            payload, _ = await self._get(
                "dexscreener",
                f"{self.cfg.dex_base}/latest/dex/search?q={quote(self.cfg.trending_search, safe='')}",
            )
            tp = self._ton_pairs(payload)
            if tp:
                any_ok = True
                pairs.extend(tp)

        if not any_ok:
            stale = await self._cache_get(stale_key)
            if stale:
                rep = _trending_from_payload(stale, cached=False, source="stale", limit=limit)
                rep.stale = True
                rep.warning = "⚠️ Live data unavailable — showing the last known trending list."
                return rep
            return TrendingReport(sort_by=sort_by, source="none", error="sources_unavailable",
                                  warning="⚠️ Trending data is temporarily unavailable. Try again shortly.")

        # Best pair per base token (dedupe), drop pairs without a usable base.
        best_by_token: Dict[str, dict] = {}
        for p in pairs:
            addr = (p.get("baseToken") or {}).get("address")
            if not addr:
                continue
            if addr not in best_by_token or self._liq(p) > self._liq(best_by_token[addr]):
                best_by_token[addr] = p

        items = list(best_by_token.values())
        if sort_by == "age":
            items.sort(key=lambda p: (p.get("pairCreatedAt") or 0), reverse=True)
        else:
            items.sort(key=lambda p: _f((p.get("volume") or {}).get("h24")) or 0.0, reverse=True)

        tokens: List[TrendingToken] = []
        for i, p in enumerate(items[:limit], 1):
            base = p.get("baseToken", {}) or {}
            tokens.append(TrendingToken(
                rank=i,
                symbol=base.get("symbol") or "?",
                name=base.get("name") or "Unknown",
                address=base.get("address") or "",
                price_usd=_f(p.get("priceUsd")),
                change_24h=_f((p.get("priceChange") or {}).get("h24")),
                volume_24h=_f((p.get("volume") or {}).get("h24")),
                liquidity_usd=_f((p.get("liquidity") or {}).get("usd")),
                pair_url=p.get("url"),
            ))

        report = TrendingReport(tokens=tokens, sort_by=sort_by, source="dexscreener")
        await self._store_good(key, stale_key, _trending_payload(report), self.cfg.trending_ttl)
        return report


# --------------------------------------------------------------------------- #
# (de)serialization helpers
# --------------------------------------------------------------------------- #
def _market_to_payload(m: TokenMarket) -> dict:
    d = asdict(m)
    for k in ("cached", "stale", "warning", "error"):
        d.pop(k, None)
    return d


def _market_from_payload(payload: dict, *, cached: bool, source: str) -> TokenMarket:
    data = dict(payload)
    safety = data.pop("safety", None)
    for k in ("cached", "stale", "warning", "error"):
        data.pop(k, None)
    data["source"] = source
    m = TokenMarket(**data)
    if isinstance(safety, dict):
        m.safety = SafetyReport(**safety)
    m.cached = cached
    return m


def _trending_payload(rep: TrendingReport) -> dict:
    return {"sort_by": rep.sort_by, "tokens": [asdict(t) for t in rep.tokens]}


def _trending_from_payload(payload: dict, *, cached: bool, source: str, limit: int) -> TrendingReport:
    tokens = [TrendingToken(**t) for t in (payload.get("tokens") or [])][:limit]
    return TrendingReport(tokens=tokens, sort_by=payload.get("sort_by", "volume"),
                          source=source, cached=cached)


# --------------------------------------------------------------------------- #
# Singleton + convenience wrappers
# --------------------------------------------------------------------------- #
_service: Optional[DexScreenerService] = None


def get_dexscreener_service() -> DexScreenerService:
    global _service
    if _service is None:
        _service = DexScreenerService()
    return _service


async def get_token_info(query: str) -> TokenMarket:
    return await get_dexscreener_service().get_token_info(query)


async def get_trending(sort_by: str = "volume", limit: int = 10) -> TrendingReport:
    return await get_dexscreener_service().get_trending(sort_by=sort_by, limit=limit)


__all__ = [
    "DexScreenerService", "DexConfig", "TokenMarket", "TrendingToken",
    "TrendingReport", "SafetyReport", "get_dexscreener_service",
    "get_token_info", "get_trending",
]


# --------------------------------------------------------------------------- #
# Self-test:  python -m services.dexscreener_service
# Hits live DexScreener/TONAPI (no key required). Redis optional.
# --------------------------------------------------------------------------- #
async def _selftest() -> None:
    svc = DexScreenerService()
    try:
        for q in ("NOT", "TON", "EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT"):
            m = await svc.get_token_info(q)
            print(f"\n/info {q[:20]} -> ok={m.ok} source={m.source} {m.symbol} "
                  f"price={m.price_usd} 24h={m.change_24h} liq={m.liquidity_usd} risk={m.safety.risk_level}")
            for flag in m.safety.flags:
                print("    " + flag)
        rep = await svc.get_trending(sort_by="volume", limit=5)
        print(f"\n/trending volume -> ok={rep.ok} source={rep.source} count={len(rep.tokens)}")
        for t in rep.tokens:
            print(f"  #{t.rank} {t.symbol} price={t.price_usd} vol={t.volume_24h}")
    finally:
        await svc.aclose()


if __name__ == "__main__":
    asyncio.run(_selftest())
