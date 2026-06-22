"""
handlers/ton_payment_handler.py — Telegram UX for TON on-chain payments.

This is the thin aiogram layer over services/ton_payments.py (which holds all the
money-critical logic). Flow:

    /pay -> "🪙 TON Payment" -> pick a plan -> CONFIRMATION SCREEN
            (exact amount + address + memo + deep link + QR + warnings)
         -> user pays in their wallet -> background monitor activates
         -> user is messaged automatically on confirmation

Safety choices:
  * The path is GATED: if TON_PAYMENTS_ENABLED is false or no wallet is set, the
    user is told to use Telegram Stars (instant) instead — never left guessing.
  * A clear TESTNET banner is shown when running on testnet, so nobody sends
    real mainnet TON to a test address.
  * The user must explicitly choose a plan and is shown an unmistakable
    "send EXACTLY this amount with EXACTLY this memo" confirmation before paying.
  * Nothing here moves funds or holds keys; it only shows instructions.
"""

from __future__ import annotations

import structlog
from aiogram import Router, types
from aiogram.filters import Command

from core.pricing import PLANS, PLAN_ORDER
from services import ton_payments as tp

logger = structlog.get_logger(__name__)
router = Router()


# --------------------------------------------------------------------------- #
# Entry: plan selection (called from pay.py's "🪙 TON Payment" button)
# --------------------------------------------------------------------------- #
async def show_plan_selection(callback_query: types.CallbackQuery) -> None:
    """Show the TON plan picker, or a clear 'unavailable' message when gated."""
    if not tp.is_configured():
        await callback_query.message.edit_text(
            "🪙 <b>TON Payments — Coming Soon</b>\n\n"
            "On-chain TON payments are being finalized and tested. In the "
            "meantime, please use <b>⭐ Telegram Stars</b> for instant, secure "
            "activation, or contact @TonGPT_Support.\n\n"
            "Thanks for your patience!",
            parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="⬅️ Back", callback_data="back_to_payment")]
            ]),
        )
        await callback_query.answer()
        return

    banner = ""
    if tp.is_testnet():
        banner = "🧪 <b>TESTNET MODE</b> — send only TESTNET TON. Do not send real funds.\n\n"

    rows = []
    for key in PLAN_ORDER:
        plan = PLANS[key]
        rows.append([types.InlineKeyboardButton(
            text=f"{plan['name']} — {plan['price_ton']} TON",
            callback_data=f"ton_plan_{key}",
        )])
    rows.append([types.InlineKeyboardButton(text="⬅️ Back", callback_data="back_to_payment")])

    await callback_query.message.edit_text(
        f"{banner}🪙 <b>Pay with TON</b>\n\n"
        "Choose a plan. You'll get an exact amount, address, and a one-tap "
        "wallet link. Your subscription activates automatically once the "
        "transfer confirms on-chain (usually under 2 minutes).",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback_query.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("ton_plan_"))
async def ton_plan_selected(callback_query: types.CallbackQuery) -> None:
    """Show the confirmation/payment screen for the chosen plan."""
    if not tp.is_configured():
        await callback_query.answer("TON payments are currently unavailable.", show_alert=True)
        return

    plan_key = callback_query.data[len("ton_plan_"):]
    if plan_key not in PLANS:
        await callback_query.answer("Unknown plan.", show_alert=True)
        return

    user_id = callback_query.from_user.id
    info = tp.payment_links(plan_key, user_id)
    tp.store_pending(user_id, plan_key, info["memo"])

    testnet_banner = ""
    if tp.is_testnet():
        testnet_banner = "🧪 <b>TESTNET</b> — use testnet TON only.\n\n"

    text = (
        f"{testnet_banner}🪙 <b>{info['plan_name']} — Pay with TON</b>\n\n"
        f"Send <b>exactly</b>:\n"
        f"💎 <b>{info['amount_ton']} TON</b>\n\n"
        f"To this address:\n<code>{info['address']}</code>\n\n"
        f"⚠️ <b>You MUST include this comment/memo</b> (tap to copy):\n"
        f"<code>{info['memo']}</code>\n\n"
        f"Without the exact memo we can't match your payment automatically.\n\n"
        f"✅ Activation is automatic once the transfer confirms.\n"
        f"⏱️ Quote valid ~60 min."
    )

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💸 Open in Tonkeeper", url=info["tonkeeper_link"])],
        [types.InlineKeyboardButton(text="✅ I've sent it", callback_data="ton_paid_ack")],
        [types.InlineKeyboardButton(text="📊 Check payment status", callback_data="ton_status")],
        [types.InlineKeyboardButton(text="❌ Cancel", callback_data="back_to_payment")],
    ])

    await callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)
    await _try_send_qr(callback_query.message, info["ton_deeplink"], info["plan_name"])
    await callback_query.answer()


async def _try_send_qr(message: types.Message, deeplink: str, plan_name: str) -> None:
    """Best-effort QR image of the ton:// deeplink. Silently skipped if the
    optional 'qrcode' dependency isn't installed."""
    try:
        import io
        import qrcode  # optional: pip install "qrcode[pil]"
        img = qrcode.make(deeplink)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        photo = types.BufferedInputFile(buf.read(), filename="ton_payment.png")
        await message.answer_photo(
            photo,
            caption=f"📷 Scan to pay for <b>{plan_name}</b> (amount + memo prefilled).",
            parse_mode="HTML",
        )
    except ModuleNotFoundError:
        logger.debug("qrcode_not_installed_skipping_qr")
    except Exception as e:  # noqa: BLE001
        logger.debug("ton_qr_failed", err=str(e))


@router.callback_query(lambda c: c.data == "ton_paid_ack")
async def ton_paid_ack(callback_query: types.CallbackQuery) -> None:
    await callback_query.answer()
    await callback_query.message.answer(
        "🙏 <b>Thank you!</b>\n\n"
        "We're now watching the blockchain for your transfer. You'll get a "
        "message here the moment it confirms (usually under 2 minutes).\n\n"
        "If it's been longer than ~10 minutes, double-check you included the "
        "exact memo, then use /payment_status or contact @TonGPT_Support.",
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data == "ton_status")
async def ton_status_cb(callback_query: types.CallbackQuery) -> None:
    await callback_query.answer()
    text = await _status_text(callback_query.from_user.id)
    await callback_query.message.answer(text, parse_mode="HTML")


@router.message(Command("payment_status"))
async def payment_status_command(message: types.Message) -> None:
    text = await _status_text(message.from_user.id)
    await message.reply(text, parse_mode="HTML")


async def _status_text(user_id: int) -> str:
    """Human-readable status: current plan + any pending TON intent."""
    # Current plan from the Engine (source of truth).
    plan = "Free"
    try:
        from services.engine_client import engine_client
        status = await engine_client.get_user_status(str(user_id))
        plan = (status.get("plan") or status.get("tier") or "Free").title()
    except Exception:
        pass

    lines = [f"📊 <b>Payment Status</b>\n", f"📋 Current plan: <b>{plan}</b>"]

    pending = tp.get_pending(user_id)
    if pending:
        pk = pending.get("plan_key")
        pname = PLANS.get(pk, {}).get("name", pk)
        lines.append(
            f"\n⏳ Pending TON payment for <b>{pname}</b>.\n"
            f"Memo: <code>{pending.get('memo')}</code>\n"
            "Activation is automatic once your transfer confirms on-chain."
        )
    else:
        lines.append("\nNo pending TON payment found.")

    if not tp.is_configured():
        lines.append("\nℹ️ TON payments are currently unavailable — use ⭐ Telegram Stars.")

    return "\n".join(lines)


def register_ton_payment_handlers(dp) -> None:
    """Register the TON payment router."""
    dp.include_router(router)
    logger.info("ton_payment_handlers_registered", enabled=tp.is_enabled(), network=tp.network())
