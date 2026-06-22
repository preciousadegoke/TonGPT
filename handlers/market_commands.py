# handlers/market_commands.py
"""
Enhanced /info and new /trending, powered by services.dexscreener_service.

Wire-in (main.py):
    from handlers.market_commands import register_market_handlers
    register_market_handlers(dp)

Remove any older /info or /whale registration that you want this to replace, so
each command is only registered once (first router wins in aiogram).

The service handles caching, DexScreener->TONAPI/CoinGecko fallback, stale data,
and safety heuristics. The handler only formats and replies.
"""

import structlog
from aiogram import Router, types
from aiogram.filters import Command

from services.dexscreener_service import (
    TokenMarket,
    TrendingReport,
    get_dexscreener_service,
)

logger = structlog.get_logger(__name__)
router = Router()

_RISK_BADGE = {"low": "🟢 LOW", "medium": "🟡 MEDIUM", "high": "🔴 HIGH", "unknown": "⚪ UNKNOWN"}


def _fmt_price(v) -> str:
    if v is None:
        return "—"
    if v == 0:
        return "$0"
    if v < 0.0001:
        return f"${v:.8f}".rstrip("0")
    if v < 1:
        return f"${v:,.6f}".rstrip("0")
    return f"${v:,.2f}"


def _fmt_big(v) -> str:
    if v is None:
        return "—"
    if v >= 1_000_000_000:
        return f"${v/1_000_000_000:,.2f}B"
    if v >= 1_000_000:
        return f"${v/1_000_000:,.2f}M"
    if v >= 1_000:
        return f"${v/1_000:,.1f}K"
    return f"${v:,.0f}"


def _chg(v) -> str:
    if v is None:
        return "—"
    arrow = "🟢▲" if v >= 0 else "🔴▼"
    return f"{arrow}{v:+.1f}%"


def _render_info(m: TokenMarket) -> str:
    if not m.ok and m.price_usd is None:
        return m.warning or "🚫 Couldn't fetch that token right now. Please try again."

    title = f"💎 <b>{m.name}</b> (<code>{m.symbol}</code>)"
    lines = [title, ""]
    lines.append(f"💵 <b>{_fmt_price(m.price_usd)}</b>   {_chg(m.change_24h)} <i>24h</i>")

    # Multi-window performance row (only when we have DexScreener perf data).
    perf = [("5m", m.change_5m), ("1h", m.change_1h), ("6h", m.change_6h), ("24h", m.change_24h)]
    perf = [(lbl, val) for lbl, val in perf if val is not None]
    if perf:
        lines.append("📈 " + "  ".join(f"<b>{lbl}</b> {_chg(val)}" for lbl, val in perf))

    lines.append("")
    if m.liquidity_usd is not None:
        lines.append(f"💧 <b>Liquidity:</b> {_fmt_big(m.liquidity_usd)}")
    if m.market_cap is not None:
        lines.append(f"🏦 <b>Market Cap:</b> {_fmt_big(m.market_cap)}")
    if m.fdv is not None:
        lines.append(f"💠 <b>FDV:</b> {_fmt_big(m.fdv)}")
    if m.volume_24h is not None:
        lines.append(f"🔄 <b>24h Volume:</b> {_fmt_big(m.volume_24h)}")
    if m.dex:
        lines.append(f"🔀 <b>DEX:</b> {m.dex}")

    # Safety block
    s = m.safety
    if s and s.flags:
        lines.append("")
        lines.append(f"🛡️ <b>Safety:</b> {_RISK_BADGE.get(s.risk_level, s.risk_level)}")
        for flag in s.flags[:5]:
            lines.append(f"   {flag}")
        lines.append("   <i>Heuristic signals — always DYOR.</i>")

    # Links
    links = []
    if m.chart_url:
        links.append(f'<a href="{m.chart_url}">📊 Chart</a>')
    if m.tonviewer_url:
        links.append(f'<a href="{m.tonviewer_url}">🔍 Tonviewer</a>')
    if links:
        lines.append("")
        lines.append(" · ".join(links))

    # Data-source footer
    if m.stale and m.warning:
        lines.append(f"\n{m.warning}")
    else:
        tag = {"cache": "⚡ cached", "ton_data": "via TONAPI/CoinGecko"}.get(m.source, m.source)
        lines.append(f"\n<i>source: {tag}</i>")
    return "\n".join(lines)


def _render_trending(rep: TrendingReport) -> str:
    if not rep.tokens:
        return rep.warning or "📉 No trending tokens right now. Try again soon."

    label = "🆕 Newest" if rep.sort_by == "age" else "🔥 Top by Volume"
    header = f"📊 <b>Trending TON Tokens</b> — {label}"
    if rep.stale and rep.warning:
        header += f"\n{rep.warning}"
    lines = [header, ""]
    for t in rep.tokens:
        vol = _fmt_big(t.volume_24h)
        chg = _chg(t.change_24h)
        name = f'<a href="{t.pair_url}">{t.symbol}</a>' if t.pair_url else t.symbol
        lines.append(f"<b>{t.rank}.</b> {name} — {_fmt_price(t.price_usd)} {chg}")
        lines.append(f"     💧 {_fmt_big(t.liquidity_usd)} · 🔄 {vol} 24h vol")
    if not rep.stale:
        lines.append(f"\n<i>source: {rep.source}</i>")
    return "\n".join(lines)


@router.message(Command("info"))
async def info_command(message: types.Message):
    """/info <symbol|address|name> — rich token summary (defaults to TON)."""
    parts = (message.text or "").split(maxsplit=1)
    query = parts[1].strip() if len(parts) > 1 else "TON"

    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        m = await get_dexscreener_service().get_token_info(query)
        logger.info("info_command", user_id=message.from_user.id, query=query,
                    source=m.source, ok=m.ok, risk=m.safety.risk_level if m.safety else None)
        await message.reply(_render_info(m), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error("info_command_failed", user_id=message.from_user.id, err=str(e), exc_info=True)
        await message.reply("🚫 Couldn't fetch token info right now. Please try again shortly.")


@router.message(Command("trending"))
async def trending_command(message: types.Message):
    """/trending [volume|age] — top 10 TON tokens."""
    parts = (message.text or "").split(maxsplit=1)
    sort_by = parts[1].strip().lower() if len(parts) > 1 else "volume"

    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        rep = await get_dexscreener_service().get_trending(sort_by=sort_by, limit=10)
        logger.info("trending_command", user_id=message.from_user.id,
                    sort_by=rep.sort_by, count=len(rep.tokens), source=rep.source)
        await message.reply(_render_trending(rep), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error("trending_command_failed", user_id=message.from_user.id, err=str(e), exc_info=True)
        await message.reply("🚫 Trending data is temporarily unavailable. Please try again shortly.")


def register_market_handlers(dp):
    dp.include_router(router)
