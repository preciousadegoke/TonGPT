# services/radar.py
"""
TonGPT Radar — the always-on public demo (docs/CATEGORY_PLAY.md, Move 1).

A supervised background loop that discovers newly created TON pairs via
DexScreener, runs each through the verdict engine, and posts the verdict card
to a public Telegram channel. Every post is a receipt: timestamped judgment on
a token minutes after it appears, before anyone asks.

Why a channel: it markets itself 24/7 (forwardable cards, searchable history),
it seeds the outcome dataset (every new pair gets a labeled starting point),
and it's the public exhibit for the track record and grant applications.

Configuration (env)
-------------------
RADAR_CHANNEL_ID          REQUIRED to enable. Channel id (-100…) or @username.
                          The bot must be an admin of the channel.
RADAR_INTERVAL            Seconds between discovery cycles (default 300).
RADAR_SEARCH_QUERIES      Comma-separated DexScreener search terms
                          (default "ton"). Discovery via search is imperfect —
                          it's the best public endpoint available; tune terms
                          or lower the interval if launches are being missed.
RADAR_MAX_AGE_HOURS       Only post pairs younger than this (default 24).
RADAR_MAX_POSTS_PER_CYCLE Flood cap per cycle (default 3).
RADAR_MIN_LIQUIDITY_USD   Skip pairs below this liquidity (default 0 — post
                          everything; the verdict flags the dust anyway).

Failure model: never raises out of the loop body; a Redis outage degrades the
dedup to in-process memory; a DexScreener outage just means a quiet cycle.
Runs under _spawn_supervised (MAIN-001) like every other long-lived task.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

try:
    from utils.redis_conn import redis_client as _redis
except Exception as _e:  # pragma: no cover - defensive
    _redis = None
    log.warning("radar_redis_unavailable", err=str(_e))

_POSTED_KEY = "radar:posted:{addr}"
_POSTED_TTL = 7 * 24 * 60 * 60          # don't re-post the same token for 7 days
_inproc_posted: Dict[str, float] = {}   # fallback dedup when Redis is down
_INPROC_MAX = 5000


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def channel_id() -> str:
    return (os.getenv("RADAR_CHANNEL_ID") or "").strip()


def radar_enabled() -> bool:
    return bool(channel_id())


def _interval() -> int:
    try:
        return max(60, int(os.getenv("RADAR_INTERVAL", "300")))
    except ValueError:
        return 300


def _queries() -> List[str]:
    raw = os.getenv("RADAR_SEARCH_QUERIES", "ton").strip()
    return [q.strip() for q in raw.split(",") if q.strip()] or ["ton"]


def _max_age_s() -> float:
    try:
        return float(os.getenv("RADAR_MAX_AGE_HOURS", "24")) * 3600
    except ValueError:
        return 24 * 3600


def _max_posts() -> int:
    try:
        return max(1, int(os.getenv("RADAR_MAX_POSTS_PER_CYCLE", "3")))
    except ValueError:
        return 3


def _min_liq() -> float:
    try:
        return float(os.getenv("RADAR_MIN_LIQUIDITY_USD", "0"))
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------- #
# Dedup — SET NX in Redis, bounded in-process fallback
# --------------------------------------------------------------------------- #
def _claim(addr: str) -> bool:
    """True exactly once per address per TTL window."""
    now = time.time()
    if _redis:
        try:
            won = _redis.set(_POSTED_KEY.format(addr=addr), "1", ex=_POSTED_TTL, nx=True)
            if won is not None and won is not False:
                return bool(won)
            return False
        except Exception as e:  # noqa: BLE001
            log.debug("radar_claim_redis_failed", err=str(e))
    # In-process fallback (evict old entries past the cap)
    if addr in _inproc_posted and now - _inproc_posted[addr] < _POSTED_TTL:
        return False
    if len(_inproc_posted) > _INPROC_MAX:
        cutoff = sorted(_inproc_posted.values())[len(_inproc_posted) // 2]
        for k in [k for k, v in _inproc_posted.items() if v <= cutoff]:
            _inproc_posted.pop(k, None)
    _inproc_posted[addr] = now
    return True


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
async def discover_new_pairs() -> List[dict]:
    """Fresh TON pairs (newest first): [{address, symbol, name, age_s, liq}]."""
    from services.dexscreener_service import get_dexscreener_service

    svc = get_dexscreener_service()
    now_ms = time.time() * 1000
    max_age_ms = _max_age_s() * 1000
    min_liq = _min_liq()

    seen: set = set()
    fresh: List[dict] = []
    for q in _queries():
        try:
            pairs = await svc.search_pairs(q)
        except Exception as e:  # noqa: BLE001
            log.warning("radar_search_failed", query=q, err=str(e))
            continue
        for p in pairs:
            base = p.get("baseToken") or {}
            addr = base.get("address")
            created = p.get("pairCreatedAt")
            if not addr or addr in seen or not created:
                continue
            age_ms = now_ms - float(created)
            if age_ms < 0 or age_ms > max_age_ms:
                continue
            liq = float(((p.get("liquidity") or {}).get("usd")) or 0.0)
            if liq < min_liq:
                continue
            seen.add(addr)
            fresh.append({
                "address": addr,
                "symbol": base.get("symbol") or "?",
                "name": base.get("name") or "?",
                "age_s": age_ms / 1000.0,
                "liq": liq,
            })
    fresh.sort(key=lambda x: x["age_s"])  # newest first
    return fresh


def _age_str(age_s: float) -> str:
    if age_s < 3600:
        return f"{age_s / 60:.0f}m"
    return f"{age_s / 3600:.1f}h"


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #
async def radar_cycle(bot) -> int:
    """One discovery+post cycle. Returns number of cards posted."""
    from services.verdict import check_token, render_card

    chan = channel_id()
    if not chan or not bot:
        return 0

    pairs = await discover_new_pairs()
    posted = 0
    for p in pairs:
        if posted >= _max_posts():
            break
        if not _claim(p["address"]):
            continue

        v = await check_token(p["address"])
        if v is None:
            # Not indexed enough to judge — say so; silence would be a gap in
            # the record. (Rendered without a full card.)
            text = (
                f"📡 <b>New TON pair</b> · {_age_str(p['age_s'])} old\n"
                f"<b>{p['symbol']}</b> — {p['name']}\n"
                f"<code>{p['address']}</code>\n\n"
                "⚪ <b>UNKNOWN — too new to judge.</b> No market data indexed "
                "yet. Unindexed tokens are the riskiest kind."
            )
        else:
            header = f"📡 <b>New TON pair</b> · {_age_str(p['age_s'])} old\n\n"
            text = header + render_card(v, bot_username=_bot_username_cache or "TonGPT_Bot", compact=True)

        try:
            await bot.send_message(chan, text, parse_mode="HTML", disable_web_page_preview=True)
            posted += 1
            await asyncio.sleep(1.5)  # stay far under channel flood limits
        except Exception as e:  # noqa: BLE001
            log.error("radar_post_failed", err=str(e), symbol=p["symbol"])
            # Don't retry this cycle; the claim stands so we never spam a
            # broken post repeatedly. The next pair still gets its shot.
    if posted:
        log.info("radar_cycle_posted", count=posted)
    return posted


_bot_username_cache: Optional[str] = None


async def radar_loop() -> None:
    """Supervised background task (spawn via _spawn_supervised in main.py)."""
    global _bot_username_cache
    if not radar_enabled():
        log.info("radar_disabled_no_channel")
        return

    from core.bot_instance import get_bot
    bot = get_bot()
    if bot and not _bot_username_cache:
        try:
            me = await bot.me()
            _bot_username_cache = me.username
        except Exception:  # noqa: BLE001
            pass

    log.info("radar_started", channel=channel_id(), interval=_interval())
    while True:
        try:
            bot = bot or get_bot()
            await radar_cycle(bot)
        except Exception as e:  # noqa: BLE001
            log.error("radar_cycle_error", err=str(e))
        await asyncio.sleep(_interval())


__all__ = ["radar_loop", "radar_cycle", "radar_enabled", "discover_new_pairs"]
