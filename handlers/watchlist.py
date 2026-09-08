# handlers/watchlist.py
"""
Personal token watchlist — /watch, /unwatch, /watchlist.

Entries live in a Redis set ``watchlist:{user_id}`` as ``SYMBOL|address``
strings (address may be empty for symbol-only entries). /watchlist renders a
live snapshot via DexScreener with concurrent fetches, so it stays fast even
at the 10-token cap.

Design notes
------------
* SafeRedisClient never raises — every Redis miss degrades to a friendly
  message, never a crash.
* /watch validates the token via get_token_info BEFORE saving, so the list
  can't fill with typos.
* Inline "🗑 Remove" buttons use callback data ``wl_del:<entry>`` (entries are
  capped well under Telegram's 64-byte callback limit).
* compare.py reuses ``add_to_watchlist`` for its "➕ Watch" buttons.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Tuple

from aiogram import F, Router, types
from aiogram.filters import Command

from utils.redis_conn import redis_client

logger = logging.getLogger(__name__)

router = Router()

WATCHLIST_MAX = 10
_KEY = "watchlist:{user_id}"


# --------------------------------------------------------------------------- #
# Formatting helpers (shared with compare.py)
# --------------------------------------------------------------------------- #
def fmt_price(v: Optional[float]) -> str:
    if v is None:
        return "—"
    if v >= 1:
        return f"${v:,.2f}"
    if v >= 0.01:
        return f"${v:.4f}"
    return f"${v:.8f}".rstrip("0")


def fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "—"
    arrow = "📈" if v >= 0 else "📉"
    return f"{arrow} {v:+.1f}%"


def fmt_usd_compact(v: Optional[float]) -> str:
    if v is None:
        return "—"
    if v >= 1_000_000_000:
        return f"${v / 1e9:.1f}B"
    if v >= 1_000_000:
        return f"${v / 1e6:.1f}M"
    if v >= 1_000:
        return f"${v / 1e3:.1f}K"
    return f"${v:,.0f}"


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
def _key(user_id: int) -> str:
    return _KEY.format(user_id=user_id)


def _decode(v) -> str:
    return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)


def _entries(user_id: int) -> List[Tuple[str, str]]:
    """Return [(symbol, address_or_empty)] for a user, sorted by symbol."""
    try:
        raw = redis_client.smembers(_key(user_id)) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("watchlist read failed for %s: %s", user_id, e)
        return []
    out: List[Tuple[str, str]] = []
    for item in raw:
        s = _decode(item)
        sym, _, addr = s.partition("|")
        if sym:
            out.append((sym, addr))
    return sorted(out)


def add_to_watchlist(user_id: int, symbol: str, address: str = "") -> Tuple[bool, str]:
    """Add an entry. Returns (ok, user_message). Reused by compare.py buttons."""
    symbol = (symbol or "").strip().upper()[:16]
    if not symbol:
        return False, "❌ No token symbol given."
    current = _entries(user_id)
    if any(sym == symbol for sym, _ in current):
        return False, f"👀 <b>{symbol}</b> is already on your watchlist."
    if len(current) >= WATCHLIST_MAX:
        return False, (
            f"📋 Your watchlist is full ({WATCHLIST_MAX} tokens).\n"
            "Remove one with /unwatch first."
        )
    try:
        redis_client.sadd(_key(user_id), f"{symbol}|{(address or '').strip()}")
    except Exception as e:  # noqa: BLE001
        logger.warning("watchlist add failed for %s: %s", user_id, e)
        return False, "⚠️ Couldn't save right now — please try again shortly."
    return True, f"✅ <b>{symbol}</b> added to your watchlist ({len(current) + 1}/{WATCHLIST_MAX}).\n💡 See it live with /watchlist"


def remove_from_watchlist(user_id: int, symbol: str) -> bool:
    symbol = (symbol or "").strip().upper()
    for sym, addr in _entries(user_id):
        if sym == symbol:
            try:
                redis_client.srem(_key(user_id), f"{sym}|{addr}")
                return True
            except Exception as e:  # noqa: BLE001
                logger.warning("watchlist remove failed for %s: %s", user_id, e)
                return False
    return False


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
@router.message(Command("watch"))
async def watch_command(message: types.Message):
    """/watch <symbol or contract address> — add a token to the watchlist."""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply(
            "👀 <b>Watch a token</b>\n\n"
            "Usage: <code>/watch NOT</code> or <code>/watch &lt;contract address&gt;</code>\n"
            "Then check prices any time with /watchlist.",
            parse_mode="HTML",
        )
        return

    query = parts[1].strip()
    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:  # noqa: BLE001
        pass

    # Validate the token exists before saving (keeps the list typo-free).
    try:
        from services.dexscreener_service import get_token_info
        market = await get_token_info(query)
    except Exception as e:  # noqa: BLE001
        logger.warning("watch lookup failed: %s", e)
        market = None

    if not market or not market.ok:
        await message.reply(
            f"🔍 I couldn't find a TON token matching <code>{query[:40]}</code>.\n"
            "Try the exact symbol (e.g. <code>/watch NOT</code>) or the contract address.",
            parse_mode="HTML",
        )
        return

    ok, msg = add_to_watchlist(message.from_user.id, market.symbol, market.address or "")
    await message.reply(msg, parse_mode="HTML")


@router.message(Command("unwatch"))
async def unwatch_command(message: types.Message):
    """/unwatch <symbol> — remove a token from the watchlist."""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply("Usage: <code>/unwatch NOT</code>", parse_mode="HTML")
        return
    symbol = parts[1].strip().upper()
    if remove_from_watchlist(message.from_user.id, symbol):
        await message.reply(f"🗑 <b>{symbol}</b> removed from your watchlist.", parse_mode="HTML")
    else:
        await message.reply(
            f"🤔 <b>{symbol}</b> isn't on your watchlist. See it with /watchlist.",
            parse_mode="HTML",
        )


@router.message(Command("watchlist", "wl"))
async def watchlist_command(message: types.Message):
    """/watchlist — live snapshot of every watched token."""
    user_id = message.from_user.id
    entries = _entries(user_id)
    if not entries:
        await message.reply(
            "📋 <b>Your watchlist is empty</b>\n\n"
            "Add tokens with <code>/watch NOT</code> — I'll keep a live list of "
            "prices, 24h moves and liquidity for you.\n\n"
            "💡 Tip: /trending shows what's hot right now.",
            parse_mode="HTML",
        )
        return

    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:  # noqa: BLE001
        pass

    from services.dexscreener_service import get_token_info

    async def _fetch(sym: str, addr: str):
        try:
            return sym, await get_token_info(addr or sym)
        except Exception as e:  # noqa: BLE001
            logger.warning("watchlist fetch failed for %s: %s", sym, e)
            return sym, None

    results = await asyncio.gather(*(_fetch(s, a) for s, a in entries))

    lines = [f"📋 <b>Your Watchlist</b> ({len(entries)}/{WATCHLIST_MAX})\n"]
    buttons: List[List[types.InlineKeyboardButton]] = []
    for sym, market in results:
        if market and market.ok:
            lines.append(
                f"<b>{sym}</b>  {fmt_price(market.price_usd)}  "
                f"{fmt_pct(market.change_24h)}  💧{fmt_usd_compact(market.liquidity_usd)}"
            )
        else:
            lines.append(f"<b>{sym}</b>  ⚠️ data unavailable right now")
        buttons.append([types.InlineKeyboardButton(text=f"🗑 Remove {sym}", callback_data=f"wl_del:{sym}")])

    lines.append("\n💡 <code>/compare " + " ".join(s for s, _ in entries[:3]) + "</code> for a side-by-side view")
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.reply("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)


# --------------------------------------------------------------------------- #
# Callbacks (also serves compare.py's "➕ Watch" buttons)
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("wl_del:"))
async def wl_del_callback(callback: types.CallbackQuery):
    symbol = callback.data.split(":", 1)[1]
    if remove_from_watchlist(callback.from_user.id, symbol):
        await callback.answer(f"{symbol} removed ✅")
    else:
        await callback.answer(f"{symbol} wasn't on your list", show_alert=False)


@router.callback_query(F.data.startswith("wl_add:"))
async def wl_add_callback(callback: types.CallbackQuery):
    payload = callback.data.split(":", 1)[1]
    sym, _, addr = payload.partition("|")
    ok, msg = add_to_watchlist(callback.from_user.id, sym, addr)
    # Strip HTML for the toast
    import re
    await callback.answer(re.sub(r"<[^>]+>", "", msg)[:190], show_alert=not ok)


def register_watchlist_handlers(dp):
    dp.include_router(router)
    logger.info("✅ Watchlist handlers registered")
