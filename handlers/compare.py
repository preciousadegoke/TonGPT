# handlers/compare.py
"""
/compare — side-by-side comparison of 2–4 TON tokens.

Fetches all tokens concurrently via the DexScreener service (cached, breaker-
protected), renders a compact metric-by-metric comparison, highlights a quick
take (best 24h performer, deepest liquidity, risk flags), and offers one-tap
"➕ Watch" buttons that feed the watchlist feature.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List

from aiogram import Router, types
from aiogram.filters import Command

from handlers.watchlist import fmt_pct, fmt_price, fmt_usd_compact

logger = logging.getLogger(__name__)

router = Router()

MAX_TOKENS = 4

_RISK_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🔴", "unknown": "⚪"}


@router.message(Command("compare"))
async def compare_command(message: types.Message):
    """/compare NOT FISH [MY] [...] — up to 4 tokens side by side."""
    parts = (message.text or "").split()
    queries = parts[1:MAX_TOKENS + 1]

    if len(queries) < 2:
        await message.reply(
            "⚖️ <b>Compare tokens side by side</b>\n\n"
            "Usage: <code>/compare NOT FISH</code> (2–4 tokens, symbols or "
            "contract addresses)\n\n"
            "You'll get price, 24h move, liquidity, volume, FDV and risk "
            "signals in one view.",
            parse_mode="HTML",
        )
        return

    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:  # noqa: BLE001
        pass

    from services.dexscreener_service import get_token_info

    async def _fetch(q: str):
        try:
            return q, await get_token_info(q)
        except Exception as e:  # noqa: BLE001
            logger.warning("compare fetch failed for %s: %s", q, e)
            return q, None

    results = await asyncio.gather(*(_fetch(q) for q in queries))

    found = [(q, m) for q, m in results if m and m.ok]
    missing = [q for q, m in results if not (m and m.ok)]

    if len(found) < 2:
        miss = ", ".join(f"<code>{q[:30]}</code>" for q in missing)
        await message.reply(
            f"🔍 I couldn't find enough of those tokens ({miss}).\n"
            "Use exact symbols (e.g. <code>NOT</code>) or contract addresses — "
            "or try /trending to discover tokens first.",
            parse_mode="HTML",
        )
        return

    # ---- Render: one block per token, identical metric order ----
    lines: List[str] = ["⚖️ <b>Token Comparison</b>\n"]
    for _, m in found:
        risk = _RISK_EMOJI.get(m.safety.risk_level, "⚪")
        flags = f" ({', '.join(m.safety.flags[:2])})" if m.safety.flags else ""
        lines.append(
            f"<b>{m.symbol}</b> — {m.name}\n"
            f"  💵 {fmt_price(m.price_usd)}   24h {fmt_pct(m.change_24h)}\n"
            f"  💧 Liq {fmt_usd_compact(m.liquidity_usd)}   "
            f"📊 Vol {fmt_usd_compact(m.volume_24h)}   "
            f"🏦 FDV {fmt_usd_compact(m.fdv)}\n"
            f"  {risk} Risk: {m.safety.risk_level}{flags}"
        )

    # ---- Quick take ----
    with_change = [(q, m) for q, m in found if m.change_24h is not None]
    with_liq = [(q, m) for q, m in found if m.liquidity_usd is not None]
    take: List[str] = []
    if with_change:
        best = max(with_change, key=lambda x: x[1].change_24h)[1]
        take.append(f"🚀 Best 24h: <b>{best.symbol}</b> ({best.change_24h:+.1f}%)")
    if with_liq:
        deep = max(with_liq, key=lambda x: x[1].liquidity_usd)[1]
        take.append(f"💧 Deepest liquidity: <b>{deep.symbol}</b> ({fmt_usd_compact(deep.liquidity_usd)})")
    risky = [m.symbol for _, m in found if m.safety.risk_level == "high"]
    if risky:
        take.append(f"⚠️ High-risk signals: <b>{', '.join(risky)}</b> — size positions accordingly")
    if take:
        lines.append("\n<b>Quick take</b>\n" + "\n".join(take))
    if missing:
        lines.append("\n🔍 Not found: " + ", ".join(q[:20] for q in missing))
    lines.append("\n<i>Market data, not financial advice. DYOR.</i>")

    # ---- One-tap watch buttons (callback data must stay ≤64 bytes) ----
    buttons: List[types.InlineKeyboardButton] = []
    for _, m in found:
        payload = f"{m.symbol}|{m.address or ''}"
        if len(f"wl_add:{payload}".encode()) > 64:
            payload = m.symbol  # fall back to symbol-only lookup
        buttons.append(
            types.InlineKeyboardButton(text=f"➕ Watch {m.symbol}", callback_data=f"wl_add:{payload}")
        )
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    )

    await message.reply("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)


def register_compare_handlers(dp):
    dp.include_router(router)
    logger.info("✅ Compare handlers registered")
