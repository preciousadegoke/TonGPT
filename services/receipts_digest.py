# services/receipts_digest.py
"""
Weekly receipts digest — SPEC-001 Phase 4. Accountability as recurring content.

Once a week, post the graded track record to the Radar channel: what got
graded, what we caught, what we missed, and how many days are anchored. Same
honesty rules as /trackrecord: denominators on every rate, misses shown
unprompted, nothing invented before data exists.

Self-disables when RADAR_CHANNEL_ID is unset or nothing is graded yet — the
digest never posts empty noise. Last-post time is stored in the shared SQLite
meta table so restarts don't double-post.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, Optional

import structlog

from services.outcome_tracker import _db

log = structlog.get_logger(__name__)

INTERVAL = int(os.getenv("RECEIPTS_DIGEST_INTERVAL", str(7 * 86400)))   # weekly
CHECK_EVERY = int(os.getenv("RECEIPTS_DIGEST_CHECK", "3600"))           # poll, s
ENABLED = os.getenv("RECEIPTS_DIGEST_ENABLED", "true").lower() != "false"

_LVL = {"high": "🔴", "medium": "🟡", "low": "🟢", "unknown": "⚪"}
_now = time.time


def set_clock(fn) -> None:
    global _now
    _now = fn or time.time


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def _week_graded_count(since: float) -> int:
    conn = _db()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM verdicts WHERE finalized_at >= ?", (since,)
        ).fetchone()[0]
    finally:
        conn.close()


def _anchored_days() -> Dict[str, int]:
    conn = _db()
    try:
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM anchors GROUP BY status").fetchall()
        except Exception:      # anchors table not created yet
            return {"computed": 0, "anchored": 0}
        out = {"computed": 0, "anchored": 0}
        for status, n in rows:
            out[status] = n
        return out
    finally:
        conn.close()


def _get_meta(key: str) -> Optional[str]:
    conn = _db()
    try:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _set_meta(key: str, value: str) -> None:
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Pure renderer
# --------------------------------------------------------------------------- #
def render_digest(st: Dict[str, Any], week_graded: int,
                  anchors: Dict[str, int], bot_username: str = "TonGPT_Bot") -> Optional[str]:
    """The weekly channel post. Returns None if there's nothing worth posting."""
    if not st or not st.get("finalized"):
        return None

    lines = ["🧾 <b>TonGPT Receipts — weekly digest</b>",
             "<i>Every verdict is graded against what actually happened. "
             "Misses included, always.</i>\n"]

    lines.append(f"📊 Graded this week: <b>{week_graded}</b> · all-time: <b>{st['finalized']}</b>")

    if st.get("recall"):
        r = st["recall"]
        lines.append(
            f"🎯 Of {r['dead_total']} tokens that died, we had flagged "
            f"<b>{r['flagged']}</b> ({r['pct']}%) before the outcome"
        )
    if st.get("false_alarm_rate"):
        fa = st["false_alarm_rate"]
        lines.append(
            f"🚨 False alarms: {fa['alive_high']} of {fa['high_total']} 🔴 calls "
            f"still alive at 30d ({fa['pct']}%)"
        )

    misses = st.get("misses") or []
    lines.append(f"📉 Misses on record: <b>{len(misses)}</b> (rated 🟢/⚪, token died)")

    cal = st.get("calibration") or {}
    if cal:
        parts = []
        for lvl in ("high", "medium", "low"):
            b = cal.get(lvl)
            if b:
                parts.append(f"{_LVL[lvl]} {b['death_rate_pct']}% ({b['dead']}/{b['total']})")
        if parts:
            lines.append("📈 30-day death rate by rating: " + " · ".join(parts))

    total_days = anchors.get("computed", 0) + anchors.get("anchored", 0)
    if total_days:
        lines.append(
            f"⛓ Merkle roots: <b>{total_days}</b> days computed, "
            f"<b>{anchors.get('anchored', 0)}</b> anchored on-chain"
        )

    lines.append(
        f"\n🔍 Full record: /trackrecord · verify any receipt: /proof — "
        f"@{bot_username}"
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Posting loop
# --------------------------------------------------------------------------- #
async def digest_once(bot) -> bool:
    """Post one digest if due AND there is graded data. Returns True if posted."""
    from services.radar import channel_id
    chan = channel_id()
    if not chan or not bot:
        return False

    now = _now()
    last = _get_meta("digest_last_posted")
    if last and now - float(last) < INTERVAL:
        return False

    from services.outcome_tracker import track_record_stats
    st = await track_record_stats()
    week = await asyncio.to_thread(_week_graded_count, now - 7 * 86400)
    anchors = await asyncio.to_thread(_anchored_days)

    username = "TonGPT_Bot"
    try:
        me = await bot.me()
        username = me.username or username
    except Exception:  # noqa: BLE001
        pass

    text = render_digest(st, week, anchors, username)
    if text is None:
        return False              # nothing graded yet — never post empty noise

    await bot.send_message(chan, text, parse_mode="HTML",
                           disable_web_page_preview=True)
    await asyncio.to_thread(_set_meta, "digest_last_posted", str(now))
    log.info("receipts_digest_posted", channel=chan, week_graded=week)
    return True


async def digest_loop() -> None:
    """Supervised background task (spawn via _spawn_supervised in main.py)."""
    if not ENABLED:
        log.info("receipts_digest_disabled", reason="RECEIPTS_DIGEST_ENABLED=false")
        return
    from services.radar import radar_enabled
    if not radar_enabled():
        log.info("receipts_digest_disabled", reason="RADAR_CHANNEL_ID not set")
        return

    from core.bot_instance import get_bot
    log.info("receipts_digest_started", interval=INTERVAL)
    while True:
        try:
            await digest_once(get_bot())
        except Exception as e:  # noqa: BLE001 — never kill the loop
            log.error("receipts_digest_error", err=str(e))
        await asyncio.sleep(CHECK_EVERY)


__all__ = ["render_digest", "digest_once", "digest_loop", "set_clock"]
