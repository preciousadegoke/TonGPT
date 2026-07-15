# services/verdict.py
"""
Verdict engine — the atomic unit of the trust-layer wedge (see docs/CATEGORY_PLAY.md).

A Verdict is a structured, calibrated judgment on a token, rendered as a
shareable Telegram card and recorded to a durable receipts ledger. Three rules
this module enforces everywhere:

1. **Calibrated language.** We NEVER say "safe". We report risk levels and the
   named signals behind them. A green verdict says "no major risk signals
   detected — not a guarantee". Wrong calls are survivable; overclaiming isn't.
2. **Every verdict is a receipt.** Each card is logged (JSONL on disk + Redis
   counters) with a timestamp and the inputs we saw, so the public track
   record ("flagged N of the last M rugs early") can be computed and later
   anchored on-chain. The ledger is append-only and crash-safe.
3. **Degrade honestly.** If market data is unavailable we return an UNKNOWN
   verdict that says so, never a guess.

Reuses services/dexscreener_service.py (cached, breaker-protected) for all
market + safety data — this module adds judgment, rendering, and memory.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

# Optional Redis (SafeRedisClient never raises).
try:
    from utils.redis_conn import redis_client as _redis
except Exception as _e:  # pragma: no cover - defensive
    _redis = None
    log.warning("verdict_redis_unavailable", err=str(_e))

LEDGER_FILE = os.getenv("VERDICT_LEDGER_FILE", os.path.join("data", "verdicts.jsonl"))
RECENT_KEY = "verdicts:recent"          # Redis list of recent verdict JSON blobs
RECENT_MAX = 200
COUNTER_KEY = "verdicts:count:{level}"  # per-level counters
TOTAL_KEY = "verdicts:count:total"

# Risk level -> (emoji, headline). Calibrated: no "safe", no certainty.
_HEADLINES = {
    "high": ("🔴", "HIGH RISK — multiple danger signals"),
    "medium": ("🟡", "CAUTION — risk signals present"),
    "low": ("🟢", "No major risk signals detected"),
    "unknown": ("⚪", "UNKNOWN — not enough data to judge"),
}

_FOOTER = (
    "\n🛡 <i>Scanned by TonGPT — forward any token or contract address to "
    "@{bot_username} to check it. Risk signals, not guarantees. DYOR.</i>"
)


@dataclass
class Verdict:
    symbol: str
    name: str
    address: Optional[str]
    risk_level: str                     # low | medium | high | unknown
    flags: List[str] = field(default_factory=list)
    price_usd: Optional[float] = None
    change_24h: Optional[float] = None
    liquidity_usd: Optional[float] = None
    volume_24h: Optional[float] = None
    fdv: Optional[float] = None
    top_holder_pct: Optional[float] = None
    source: str = "none"
    stale: bool = False
    checked_at: float = field(default_factory=time.time)
    verdict_id: str = ""

    def __post_init__(self):
        if not self.verdict_id:
            basis = f"{self.address or self.symbol}|{int(self.checked_at)}|{self.risk_level}"
            self.verdict_id = hashlib.sha256(basis.encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# Core: produce a verdict for a query (symbol, address, or pasted text)
# --------------------------------------------------------------------------- #
async def check_token(query: str) -> Optional[Verdict]:
    """Resolve a token and produce a Verdict. Returns None only if the token
    can't be found at all (caller renders a 'not found' message)."""
    query = (query or "").strip()
    if not query:
        return None
    try:
        from services.dexscreener_service import get_token_info
        m = await get_token_info(query)
    except Exception as e:  # noqa: BLE001
        log.warning("verdict_lookup_failed", query=query[:40], err=str(e))
        return None

    if not m or not m.ok:
        return None

    v = Verdict(
        symbol=m.symbol,
        name=m.name,
        address=m.address,
        risk_level=m.safety.risk_level if m.safety else "unknown",
        flags=list(m.safety.flags) if m.safety else [],
        price_usd=m.price_usd,
        change_24h=m.change_24h,
        liquidity_usd=m.liquidity_usd,
        volume_24h=m.volume_24h,
        fdv=m.fdv,
        top_holder_pct=m.safety.top_holder_pct if m.safety else None,
        source=m.source,
        stale=bool(m.stale),
    )
    await _record(v)
    return v


# --------------------------------------------------------------------------- #
# Rendering — the shareable card
# --------------------------------------------------------------------------- #
def _fmt_price(x: Optional[float]) -> str:
    if x is None:
        return "—"
    if x >= 1:
        return f"${x:,.2f}"
    if x >= 0.01:
        return f"${x:.4f}"
    return f"${x:.8f}".rstrip("0")


def _fmt_usd(x: Optional[float]) -> str:
    if x is None:
        return "—"
    if x >= 1e9:
        return f"${x / 1e9:.1f}B"
    if x >= 1e6:
        return f"${x / 1e6:.1f}M"
    if x >= 1e3:
        return f"${x / 1e3:.1f}K"
    return f"${x:,.0f}"


def render_card(v: Verdict, bot_username: str = "TonGPT_Bot", compact: bool = False) -> str:
    """Render a verdict as a Telegram HTML card.

    compact=True is the Group Guardian format (shorter, still branded).
    """
    emoji, headline = _HEADLINES.get(v.risk_level, _HEADLINES["unknown"])
    change = f" ({v.change_24h:+.1f}% 24h)" if v.change_24h is not None else ""
    lines = [
        f"{emoji} <b>{headline}</b>",
        f"<b>{v.symbol}</b> — {v.name}",
        f"💵 {_fmt_price(v.price_usd)}{change}   💧 Liq {_fmt_usd(v.liquidity_usd)}   "
        f"📊 Vol {_fmt_usd(v.volume_24h)}",
    ]

    flags = v.flags[:3] if compact else v.flags
    if flags:
        lines.append("")
        lines.extend(flags)
    if not compact and v.address:
        lines.append(f"\n<code>{v.address}</code>")
    if v.stale:
        lines.append("\n⚠️ <i>Live data unavailable — showing last-known values.</i>")
    lines.append(
        f"\n🧾 receipt <code>{v.verdict_id}</code> · "
        f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(v.checked_at))} · "
        f"verify: /proof {v.verdict_id}"
    )
    lines.append(_FOOTER.format(bot_username=bot_username))
    return "\n".join(lines)


def render_not_found(query: str) -> str:
    return (
        f"🔍 I couldn't find a TON token matching <code>{query[:40]}</code>.\n"
        "If it's very new it may not be indexed yet — try again in a few "
        "minutes, or send the exact contract address.\n\n"
        "⚪ <i>No data is itself a signal: unindexed tokens are the riskiest "
        "kind. Don't ape what can't be checked.</i>"
    )


# --------------------------------------------------------------------------- #
# Receipts ledger — append-only JSONL + Redis counters
# --------------------------------------------------------------------------- #
def _ledger_append(payload: Dict[str, Any]) -> None:
    d = os.path.dirname(LEDGER_FILE)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(LEDGER_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


async def _record(v: Verdict) -> None:
    """Best-effort, never raises. Disk first (durable), Redis second (fast)."""
    payload = asdict(v)
    # SPEC-001 §3.1: full canonical content hash — the Merkle leaf for the
    # daily on-chain anchor (Phase 3) and the id `/proof` will verify against.
    try:
        from services.outcome_tracker import canonical_hash
        payload["verdict_hash"] = canonical_hash(payload)
    except Exception as e:  # noqa: BLE001 — hashing must never block a verdict
        log.warning("verdict_hash_failed", err=str(e))
    try:
        await asyncio.to_thread(_ledger_append, payload)
    except Exception as e:  # noqa: BLE001
        log.warning("verdict_ledger_write_failed", err=str(e))
    if not _redis:
        return
    try:
        def _redis_write():
            _redis.incr(TOTAL_KEY)
            _redis.incr(COUNTER_KEY.format(level=v.risk_level))
            _redis.rpush(RECENT_KEY, json.dumps(payload, ensure_ascii=False))
            _redis.ltrim(RECENT_KEY, -RECENT_MAX, -1)
        await asyncio.to_thread(_redis_write)
    except Exception as e:  # noqa: BLE001
        log.warning("verdict_counters_failed", err=str(e))


def _decode(x) -> str:
    return x.decode() if isinstance(x, (bytes, bytearray)) else str(x)


async def stats() -> Dict[str, Any]:
    """Track-record stats for /receipts. Redis counters with file fallback."""
    out: Dict[str, Any] = {"total": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0, "recent": []}
    got_redis = False
    if _redis:
        try:
            def _read():
                total = _redis.get(TOTAL_KEY)
                levels = {lvl: _redis.get(COUNTER_KEY.format(level=lvl))
                          for lvl in ("high", "medium", "low", "unknown")}
                recent = _redis.lrange(RECENT_KEY, -5, -1) or []
                return total, levels, recent
            total, levels, recent = await asyncio.to_thread(_read)
            if total:
                out["total"] = int(_decode(total))
                for lvl, val in levels.items():
                    out[lvl] = int(_decode(val)) if val else 0
                for item in recent:
                    try:
                        out["recent"].append(json.loads(_decode(item)))
                    except Exception:  # noqa: BLE001
                        continue
                got_redis = True
        except Exception as e:  # noqa: BLE001
            log.warning("verdict_stats_redis_failed", err=str(e))
    if not got_redis:
        # Fall back to counting the ledger file (slower, still correct).
        def _count():
            if not os.path.exists(LEDGER_FILE):
                return
            with open(LEDGER_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    out["total"] += 1
                    lvl = rec.get("risk_level", "unknown")
                    out[lvl] = out.get(lvl, 0) + 1
                    out["recent"].append(rec)
            out["recent"] = out["recent"][-5:]
        try:
            await asyncio.to_thread(_count)
        except Exception as e:  # noqa: BLE001
            log.warning("verdict_stats_file_failed", err=str(e))
    return out


__all__ = ["Verdict", "check_token", "render_card", "render_not_found", "stats", "LEDGER_FILE"]
