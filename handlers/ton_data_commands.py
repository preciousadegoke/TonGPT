# handlers/ton_data_commands.py
"""
Example /info and /whale handlers built on services.ton_data_service.

How to wire this in (main.py)
-----------------------------
    from handlers.ton_data_commands import register_ton_data_handlers
    register_ton_data_handlers(dp)

To REPLACE the legacy /whale: remove the old `register_whale_handlers(dp)` call
(or its `@router.message(Command("whale"))`) so the command isn't registered
twice. Then this module owns /info and /whale.

The service does all the heavy lifting (caching, fallback, stale data, circuit
breaking); the handler is only responsible for formatting and replying.
"""

import structlog
from aiogram import Router, types
from aiogram.filters import Command

from services.ton_data_service import (
    TokenInfo,
    WhaleReport,
    get_ton_data_service,
)

logger = structlog.get_logger(__name__)
router = Router()

WHALE_EMOJI = {
    "mega_whale": "🚨",
    "large_whale": "🔴",
    "medium_whale": "🟠",
    "small_whale": "🟡",
    "regular": "⚪",
}


def _fmt_usd(value, digits: int = 2) -> str:
    if value is None:
        return "—"
    if value >= 1_000_000:
        return f"${value/1_000_000:,.2f}M"
    if value >= 1_000:
        return f"${value/1_000:,.2f}K"
    return f"${value:,.{digits}f}"


def _fmt_change(change) -> str:
    if change is None:
        return ""
    arrow = "🟢▲" if change >= 0 else "🔴▼"
    return f"{arrow} {change:+.2f}% (24h)"


def _render_info(info: TokenInfo) -> str:
    if info.error and info.price_usd is None:
        return info.warning or "🚫 Couldn't fetch that token right now. Please try again."

    lines = [f"💎 <b>{info.name}</b> (<code>{info.symbol}</code>)"]
    if info.price_usd is not None:
        price = f"${info.price_usd:,.4f}" if info.price_usd < 1 else f"${info.price_usd:,.2f}"
        lines.append(f"💵 <b>Price:</b> {price}")
    if info.change_24h is not None:
        lines.append(f"📊 {_fmt_change(info.change_24h)}")
    if info.market_cap_usd is not None:
        lines.append(f"🏦 <b>Market Cap:</b> {_fmt_usd(info.market_cap_usd)}")
    if info.volume_24h_usd is not None:
        lines.append(f"🔄 <b>24h Volume:</b> {_fmt_usd(info.volume_24h_usd)}")
    if info.holders is not None:
        lines.append(f"👥 <b>Holders:</b> {info.holders:,}")
    if info.verified is not None:
        lines.append(f"{'✅ Verified' if info.verified else '⚠️ Unverified'} jetton")
    if info.address:
        lines.append(f"🔗 <code>{info.address}</code>")

    # Transparency footer: where the data came from.
    tag = {"stale": "⚠️ cached (stale)", "cache": "⚡ cached"}.get(info.source)
    if info.stale and info.warning:
        lines.append(f"\n{info.warning}")
    elif tag:
        lines.append(f"\n<i>{tag}</i>")
    else:
        lines.append(f"\n<i>source: {info.source}</i>")
    return "\n".join(lines)


def _render_whales(report: WhaleReport) -> str:
    if not report.movements:
        return report.warning or "🐋 No whale movements found right now."

    header = "🐋 <b>Recent Whale Movements</b>"
    if report.stale and report.warning:
        header += f"\n{report.warning}"
    lines = [header, ""]
    for i, m in enumerate(report.movements, 1):
        emoji = WHALE_EMOJI.get(m.category, "⚪")
        usd = f" ({_fmt_usd(m.usd_value)})" if m.usd_value else ""
        lines.append(f"{i}. {emoji} <b>{m.amount_ton:,.0f} {m.kind}</b>{usd}")
        lines.append(f"   <code>{m.from_address[:8]}…</code> → <code>{m.to_address[:8]}…</code>")
    if not report.stale:
        lines.append(f"\n<i>source: {report.source}</i>")
    return "\n".join(lines)


@router.message(Command("info"))
async def info_command(message: types.Message):
    """/info <symbol|address> — token price & market data. Defaults to TON."""
    parts = (message.text or "").split(maxsplit=1)
    query = parts[1].strip() if len(parts) > 1 else "TON"

    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        info = await get_ton_data_service().get_token_info(query)
        logger.info("info_command", user_id=message.from_user.id, query=query,
                    source=info.source, ok=info.ok, stale=info.stale)
        await message.reply(_render_info(info), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error("info_command_failed", user_id=message.from_user.id, err=str(e), exc_info=True)
        await message.reply("🚫 Couldn't fetch token info right now. Please try again shortly.")


@router.message(Command("whale"))
async def whale_command(message: types.Message):
    """/whale [limit] — recent large TON movements."""
    parts = (message.text or "").split(maxsplit=1)
    limit = 5
    if len(parts) > 1 and parts[1].strip().isdigit():
        limit = int(parts[1].strip())

    await message.reply("🐋 <b>Scanning for whale movements…</b>", parse_mode="HTML")
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        report = await get_ton_data_service().get_whale_movements(limit=limit)
        logger.info("whale_command", user_id=message.from_user.id, count=len(report.movements),
                    source=report.source, stale=report.stale)
        await message.answer(_render_whales(report), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error("whale_command_failed", user_id=message.from_user.id, err=str(e), exc_info=True)
        await message.answer("🚫 Whale tracking is temporarily unavailable. Please try again shortly.")


def register_ton_data_handlers(dp):
    dp.include_router(router)
