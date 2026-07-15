# handlers/verify.py
"""
Forward-to-verify + Group Guardian — the distribution surface of the trust
layer (docs/CATEGORY_PLAY.md).

Three entry points, one engine (services/verdict.py):

* /check <symbol|address>       — explicit check, works everywhere (also as a
                                  reply to a message containing an address)
* forward-to-verify (private)   — ANY private message containing a TON contract
                                  address (typed, pasted, or forwarded from a
                                  shill group) gets a full verdict card
* Group Guardian (groups)       — added to a group, the bot watches for
                                  contract addresses and replies with a compact
                                  verdict card; per-address cooldown so it
                                  never spams. It stays silent otherwise.

REGISTRATION ORDER MATTERS: this module must be registered BEFORE gpt_reply in
HANDLER_MODULES so address-bearing private messages get a verdict card instead
of a generic GPT answer.

Guardian note: with Telegram bot privacy mode ON, the bot only sees commands,
replies and mentions in groups. For full guardian coverage, group admins add
the bot as admin (or the operator disables privacy mode via @BotFather).
/guardian explains this to users.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import List, Optional

from aiogram import F, Router, types
from aiogram.filters import Command

from utils.redis_conn import redis_client

logger = logging.getLogger(__name__)

router = Router()

# TON address shapes: friendly base64url (EQ…/UQ…, 48 chars) and raw 0:<hex64>.
_ADDR_RE = re.compile(r"\b(?:[EU]Q[A-Za-z0-9_-]{46}|-?0:[0-9a-fA-F]{64})\b")

GUARDIAN_COOLDOWN = 900       # seconds before re-verdicting the same address in a chat
GUARDIAN_CHAT_RATE = 4        # max guardian cards per chat per minute
MAX_ADDRS_PER_MESSAGE = 2

_bot_username: Optional[str] = None


async def _username(message: types.Message) -> str:
    """Cache the bot username for card footers."""
    global _bot_username
    if not _bot_username:
        try:
            me = await message.bot.me()
            _bot_username = me.username or "TonGPT_Bot"
        except Exception:  # noqa: BLE001
            _bot_username = "TonGPT_Bot"
    return _bot_username


def _extract_addresses(message: types.Message) -> List[str]:
    text = " ".join(filter(None, [message.text, message.caption]))
    seen, out = set(), []
    for m in _ADDR_RE.finditer(text or ""):
        addr = m.group(0)
        if addr not in seen:
            seen.add(addr)
            out.append(addr)
    return out[:MAX_ADDRS_PER_MESSAGE]


def _has_address(message: types.Message) -> bool:
    text = " ".join(filter(None, [message.text, message.caption]))
    return bool(_ADDR_RE.search(text or ""))


async def _send_verdict(message: types.Message, query: str, compact: bool = False) -> None:
    from services.verdict import check_token, render_card, render_not_found

    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:  # noqa: BLE001
        pass

    v = await check_token(query)
    username = await _username(message)
    if v is None:
        await message.reply(render_not_found(query), parse_mode="HTML")
        return
    await message.reply(render_card(v, bot_username=username, compact=compact), parse_mode="HTML")


# --------------------------------------------------------------------------- #
# /check — explicit, works in private and groups
# --------------------------------------------------------------------------- #
@router.message(Command("check", "scan_token", "verify"))
async def check_command(message: types.Message):
    parts = (message.text or "").split(maxsplit=1)
    query = parts[1].strip() if len(parts) > 1 else ""

    # Used as a reply: check the replied-to message's address/text instead.
    if not query and message.reply_to_message:
        addrs = _extract_addresses(message.reply_to_message)
        if addrs:
            query = addrs[0]
        else:
            replied = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()
            query = replied.split()[0] if replied else ""

    if not query:
        await message.reply(
            "🛡 <b>Check a token</b>\n\n"
            "Usage: <code>/check NOT</code> or <code>/check &lt;contract address&gt;</code>\n"
            "…or just forward me any message that contains a contract address.\n"
            "In groups, reply to a shill message with /check.",
            parse_mode="HTML",
        )
        return
    await _send_verdict(message, query, compact=(message.chat.type != "private"))


# --------------------------------------------------------------------------- #
# /receipts + /trackrecord moved to handlers/trackrecord.py (SPEC-001 Phase 2):
# the graded card — recall, false alarms, misses, calibration — replaces the
# issued-counts-only view that lived here.
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# /guardian — pitch + setup instructions
# --------------------------------------------------------------------------- #
@router.message(Command("guardian"))
async def guardian_command(message: types.Message):
    username = await _username(message)
    await message.reply(
        "🛡 <b>Group Guardian</b>\n\n"
        f"Add @{username} to your trading group and it will automatically scan "
        "every contract address posted there — replying with a risk verdict "
        "within seconds, before anyone apes in.\n\n"
        "<b>Setup (30 seconds):</b>\n"
        f"1. Add @{username} to the group\n"
        "2. Make it admin (so it can see all messages)\n"
        "3. Done — it only speaks when it sees a contract address\n\n"
        "It never posts ads, never DMs your members, and rate-limits itself. "
        "Use /check as a reply to any message to trigger a scan manually.\n\n"
        "🤖 <b>Building an AI agent or trading bot?</b> The same verdicts are "
        "available as a machine-readable pre-trade gate — a keyed API "
        "(<code>/api/guardian/check</code>) and a zero-dependency MCP server "
        "(<code>scripts/guardian-mcp</code>) built for TON Agentic Wallets. "
        "Calibrated <code>block/warn/pass</code> advice with our graded track "
        "record attached, and every answer is a receipt you can verify with "
        "/proof. Contact the operator for an API key.",
        parse_mode="HTML",
    )


# --------------------------------------------------------------------------- #
# /radar — point users at the public Radar channel
# --------------------------------------------------------------------------- #
@router.message(Command("radar"))
async def radar_command(message: types.Message):
    import os
    link = (os.getenv("RADAR_CHANNEL_LINK") or "").strip()
    if not link:
        chan = (os.getenv("RADAR_CHANNEL_ID") or "").strip()
        if chan.startswith("@"):
            link = f"https://t.me/{chan[1:]}"
    if link:
        await message.reply(
            "📡 <b>TonGPT Radar</b>\n\n"
            "Every new TON pair, scanned and verdict-stamped minutes after it "
            f"appears — before anyone shills it to you.\n\n👉 {link}",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    else:
        await message.reply(
            "📡 The Radar channel isn't live yet — soon: every new TON pair, "
            "auto-scanned the moment it appears. Meanwhile, /check any token "
            "or forward me any shill message."
        )


# --------------------------------------------------------------------------- #
# Forward-to-verify — private messages containing a contract address
# --------------------------------------------------------------------------- #
@router.message(F.chat.type == "private", F.text | F.caption, _has_address)
async def private_address_scan(message: types.Message):
    """Any private message with a TON address (typed or forwarded) → verdict."""
    for addr in _extract_addresses(message):
        await _send_verdict(message, addr, compact=False)


# --------------------------------------------------------------------------- #
# Group Guardian — group messages containing a contract address
# --------------------------------------------------------------------------- #
def _cooldown_key(chat_id: int, addr: str) -> str:
    h = hashlib.sha256(addr.encode()).hexdigest()[:16]
    return f"guardian:cd:{chat_id}:{h}"


def _chat_rate_ok(chat_id: int) -> bool:
    """Cheap per-chat rate cap: max GUARDIAN_CHAT_RATE cards/minute."""
    try:
        key = f"guardian:rate:{chat_id}"
        n = redis_client.incr(key)
        if n == 1:
            redis_client.expire(key, 60)
        return int(n or 0) <= GUARDIAN_CHAT_RATE
    except Exception:  # noqa: BLE001
        return True  # rate cap is a nicety; the address cooldown still holds


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text | F.caption, _has_address)
async def guardian_scan(message: types.Message):
    """Silently watch groups; verdict each new contract address, then shut up."""
    chat_id = message.chat.id
    for addr in _extract_addresses(message):
        # Per-(chat,address) cooldown — atomic SET NX EX so concurrent posts
        # of the same contract produce exactly one card.
        try:
            won = redis_client.set(_cooldown_key(chat_id, addr), "1", ex=GUARDIAN_COOLDOWN, nx=True)
        except Exception:  # noqa: BLE001
            won = True  # Redis down → still scan; worst case an extra card
        if not won:
            continue
        if not _chat_rate_ok(chat_id):
            logger.info("guardian rate-capped in chat %s", chat_id)
            return
        await _send_verdict(message, addr, compact=True)


def register_verify_handlers(dp):
    dp.include_router(router)
    logger.info("✅ Verify/Guardian handlers registered")
