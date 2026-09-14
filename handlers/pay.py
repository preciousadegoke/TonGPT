from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import LabeledPrice, PreCheckoutQuery, Message
import logging
import os
import hashlib
import time
import httpx
from services.engine_client import engine_client
from utils.redis_conn import redis_client

logger = logging.getLogger(__name__)
router = Router()

# Payment configuration
PAYMENT_TOKEN = os.getenv("PAYMENT_TOKEN")

# FIX-2: Contract address for TonConnect deep links
CONTRACT_ADDRESS = "0QBeYwn1b3YMHrcF07KwXx3GNbktcvAJ_8ByAlZKZMdHOO5H"
TONCENTER_BASE_URL = "https://testnet.toncenter.com/api/v2"

# Pricing is defined in ONE place — core/pricing.py — and imported everywhere
# (pay.py, services/ton_payments.py, the docs) so the numbers can never drift.
# expected_stars()/expected_nanoton() are the canonical per-tier amounts.
from core.pricing import PLANS, expected_stars, expected_nanoton  # single source of truth


async def validate_payment_amount(
    invoice_payload: str, total_amount: int, currency: str
) -> str:
    """Validate a paid invoice against the canonical price for its plan.

    ``total_amount`` is whatever Telegram reports in ``successful_payment``:
      * currency == "XTR": the WHOLE number of Stars (no subunit) → compare to
        ``expected_stars`` directly. (The previous USD-estimate math here was a
        no-op because of the ×100 invoice bug — see core/pricing.py XTR rule.)
      * currency == "TON": Telegram-native TON amount in nanoton (smallest unit)
        → compare to ``expected_nanoton``.
    Raises ValueError on an unknown plan, unsupported currency, or underpayment.
    """
    plan_key = invoice_payload
    if plan_key not in PLANS:
        raise ValueError(f"Unknown plan: {plan_key}")

    if currency == "XTR":
        expected = int(expected_stars(plan_key))
        if int(total_amount) < expected:
            raise ValueError(
                f"Underpayment: paid {total_amount} Stars, expected {expected} Stars"
            )
    elif currency == "TON":
        expected = int(expected_nanoton(plan_key))
        if int(total_amount) < expected:
            raise ValueError(
                f"Underpayment: paid {total_amount} nanoton, expected {expected} nanoton"
            )
    else:
        raise ValueError(f"Unsupported currency: {currency}")

    return plan_key


# Display emoji per tier (presentation only — never a source of price data).
_PLAN_EMOJI = {"starter": "🥉", "pro": "🥈", "pro_plus": "🥇", "elite": "💎"}


def _build_payment_keyboard(user_id: int) -> types.InlineKeyboardMarkup:
    """Build the plan-selection keyboard with Star prices read from PLANS.

    Button labels are NEVER hardcoded — every price is rendered from
    core/pricing.py so the displayed amount always equals the invoice amount.
    """
    from core.pricing import PLAN_ORDER

    plan_buttons = [
        types.InlineKeyboardButton(
            text=f"{_PLAN_EMOJI.get(k, '📦')} {PLANS[k]['name'].replace(' Plan', '')} - {PLANS[k]['price_stars']}⭐",
            callback_data=f"pay_stars_{k}",
        )
        for k in PLAN_ORDER
    ]
    rows = [plan_buttons[i:i + 2] for i in range(0, len(plan_buttons), 2)]
    rows.append([
        types.InlineKeyboardButton(text="🪙 TON Payment", callback_data="pay_ton"),
        types.InlineKeyboardButton(text="ℹ️ Plan Details", callback_data="plan_details"),
    ])
    rows.append([
        types.InlineKeyboardButton(text="🎁 Referrals", callback_data="referrals"),
        types.InlineKeyboardButton(text="📊 Check Status", callback_data=f"check_status_{user_id}"),
    ])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


async def _activate_with_resilience(
    *, user_id: int, engine_plan: str, provider: str,
    charge_id: str, duration_days: int, plan_key: str,
    amount_stars: int = 0, amount_ton: float = 0.0,
    checkout_reference: str | None = None,
) -> dict:
    """Activate a subscription with Postgres as the single source of truth.

    Flow:
      1. Attempt the ATOMIC record+activate in Postgres (idempotent, retried).
      2. If that fails for a *transient* reason (Engine/network down), persist
         the activation to a durable on-disk queue so a background loop can
         finish it later. We do NOT depend on Redis for this — Redis may be the
         very thing that's down.
      3. If it fails *permanently* (e.g. invalid plan), do not queue; surface it.

    Returns the normalized result dict from EngineClient.complete_payment, with
    an extra ``queued: True`` flag when it was deferred to the durable queue.

    IMPORTANT: a subscription is NEVER granted without a confirmed payment row in
    Postgres — activation only happens inside Payment/complete's transaction.
    """
    try:
        result = await engine_client.complete_payment(
            telegram_id=user_id,
            plan=engine_plan,
            provider=provider,
            external_id=charge_id,
            duration_days=duration_days,
            amount_ton=amount_ton,
            amount_stars=amount_stars,
            **({'checkout_reference': checkout_reference} if checkout_reference else {}),
        )
    except Exception as e:
        logger.error(f"complete_payment raised for user {user_id}: {e}")
        result = {"ok": False, "permanent": False, "error": str(e)}

    if result.get("ok"):
        # Reset the daily usage counter (best-effort; not a source of truth).
        try:
            if redis_client:
                redis_client.delete(f"usage_today:{user_id}")
        except Exception as e:
            logger.debug(f"usage reset skipped: {e}")
        return result

    if result.get("permanent"):
        logger.error(
            f"Permanent activation failure user={user_id} plan={plan_key}: "
            f"{result.get('message') or result.get('error')}"
        )
        return result

    # Transient failure — durably queue for background reconciliation.
    try:
        from services.activation_queue import enqueue
        await enqueue({
            "user_id": user_id,
            "plan": engine_plan,
            "provider": provider,
            "external_id": charge_id,
            "duration_days": duration_days,
            "plan_key": plan_key,
            # Carry the amount so the queue drain re-validates correctly (PAY-001).
            "amount_stars": amount_stars,
            "amount_ton": amount_ton,
            **({'checkout_reference': checkout_reference} if checkout_reference else {}),
        })
        result["queued"] = True
    except Exception as e:
        # Last-resort: even queueing failed. Log loudly so ops can recover from
        # the structured payment_received log + Telegram's own payment record.
        logger.critical(
            f"ACTIVATION_LOST_RISK user={user_id} plan={plan_key} "
            f"charge_id={charge_id}: failed to queue activation: {e}"
        )
        result["queued"] = False
    return result


def _success_message(plan: dict) -> str:
    """Build the upgrade-confirmation message for a freshly activated plan."""
    msg = (
        f"✅ <b>Payment Successful!</b>\n\n"
        f"🎯 <b>Plan:</b> {plan['name']}\n"
        f"⏱️ <b>Duration:</b> {plan['duration_days']} days\n\n"
        f"🚀 <b>Your new features:</b>\n"
    )
    for feature in plan["features"]:
        msg += f"• {feature}\n"
    msg += (
        f"\n💡 <b>Try these commands:</b>\n"
        f"/scan - Enhanced token analysis\n"
        f"/whale - Premium whale alerts\n"
        f"/stats - Check your subscription\n\n"
        f"🎉 Welcome to TonGPT Premium!"
    )
    return msg

# PLANS is imported from core.pricing (single source of truth) — see the import
# near the top of this file. Do not redefine pricing here.

@router.message(Command("pay", "subscribe"))
async def pay_command(message: types.Message):
    """Handle payment command with multiple options"""
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "User"
    
    # Check current user status
    current_plan = await get_user_plan(user_id)
    
    payment_msg = (
        f"💎 <b>TonGPT Premium Plans</b>\n\n"
        f"👤 <b>User:</b> {user_name} (ID: {user_id})\n"
        f"📋 <b>Current Plan:</b> {current_plan}\n\n"
        f"🌟 <b>Payment via Telegram Stars</b>\n"
        f"💰 Easy, instant, and secure!\n\n"
        f"📦 <b>Available Plans:</b>\n"
    )
    
    # Add plan details
    for plan_key, plan in PLANS.items():
        features_text = "\n".join([f"  • {feature}" for feature in plan["features"][:3]])
        payment_msg += (
            f"\n🎯 <b>{plan['name']}</b> - {plan['price_stars']} ⭐\n"
            f"{features_text}\n"
        )
    
    payment_msg += (
        f"\n💳 <b>Payment Methods:</b>\n"
        f"⭐ Telegram Stars (instant)\n"
        f"🪙 TON Wallet (manual)\n"
        f"💎 Crypto payments (manual)\n\n"
        f"🎁 <b>Special:</b> Use /refer to earn free access!"
    )
    
    # Inline keyboard with payment options (prices rendered from core/pricing.py).
    keyboard = _build_payment_keyboard(user_id)

    await message.reply(payment_msg, parse_mode="HTML", reply_markup=keyboard)

# Telegram Stars Payment Handlers
@router.callback_query(lambda c: c.data.startswith("pay_stars_"))
async def handle_stars_payment(callback_query: types.CallbackQuery):
    """Handle Telegram Stars payment.

    Telegram Stars (currency "XTR") are a native Telegram payment method and take
    NO payment provider — ``provider_token`` MUST be empty. PAYMENT_TOKEN is only
    for third-party fiat providers and is irrelevant here, so the Stars path is
    available regardless of whether PAYMENT_TOKEN is set.
    """
    plan_key = callback_query.data.split("pay_stars_")[-1]
    plan = PLANS.get(plan_key)

    if not plan:
        await callback_query.answer("Invalid plan", show_alert=True)
        return

    # XTR amount is the WHOLE number of Stars — never ×100 (see core/pricing.py
    # XTR rule). expected_stars() is the single source of truth for this value.
    prices = [LabeledPrice(label=f"{plan['name']} (1 month)", amount=expected_stars(plan_key))]

    await callback_query.bot.send_invoice(
        chat_id=callback_query.message.chat.id,
        title=f"TonGPT {plan['name']}",
        description=f"Upgrade to {plan['name']} for premium features:\n" +
                   "\n".join([f"• {feature}" for feature in plan['features']]),
        payload=f"premium_{plan_key}",
        provider_token="",          # REQUIRED empty for Telegram Stars (XTR)
        currency="XTR",             # Telegram Stars
        prices=prices,
        start_parameter="TonGPT",
        need_email=False,
        need_phone_number=False,
        need_shipping_address=False,
        is_flexible=False
    )

    await callback_query.answer("Invoice sent!")

@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    """Handle pre-checkout validation"""
    payload = pre_checkout_query.invoice_payload
    
    # Strip premium_ prefix if present, but validate ALL payloads
    from services.checkout import parse_invoice
    try:
        plan_key, _ = parse_invoice(payload, pre_checkout_query.from_user.id)
    except ValueError:
        await pre_checkout_query.answer(ok=False, error_message="This invoice belongs to another user. Open checkout in your own account.")
        return
    if plan_key in PLANS:
        await pre_checkout_query.answer(ok=True)
        return
    
    await pre_checkout_query.answer(
        ok=False, 
        error_message="Invalid payment plan"
    )

@router.message(lambda message: message.successful_payment is not None)
async def successful_payment_handler(message: Message):
    """Handle successful Telegram Stars payment"""
    user_id = message.from_user.id
    payment = message.successful_payment
    
    # Strip premium_ prefix if present, but validate ALL payloads
    raw_payload = payment.invoice_payload
    from services.checkout import parse_invoice
    
    try:
        raw_plan_key, checkout_reference = parse_invoice(raw_payload, user_id)
        validated_plan = await validate_payment_amount(
            raw_plan_key, payment.total_amount, payment.currency
        )
    except ValueError as e:
        logger.error(f"Payment validation failed for user {user_id}: {e}")
        await message.reply(
            "⚠️ Payment underpaid or invalid. No activation was performed. Please contact support.",
            parse_mode="HTML",
        )
        return

    plan_key = validated_plan
    plan = PLANS.get(plan_key)

    if not plan:
        # Should be impossible (validate_payment_amount already checked), but
        # never silently drop a paid order.
        logger.error(f"Validated plan missing from PLANS: {plan_key} (user {user_id})")
        await message.reply(
            "✅ <b>Payment received.</b> We're finalizing your upgrade — if it isn't "
            f"active shortly, contact @TonGPT_Support with User ID <code>{user_id}</code>.",
            parse_mode="HTML",
        )
        return

    # Idempotency key: Telegram's charge id is globally unique per payment.
    # Postgres (via the unique index on ExternalId) is the idempotency authority
    # — NOT Redis. A deterministic fallback keeps retries dedupable in the
    # (extremely unlikely) case Telegram omits the charge id.
    charge_id = (getattr(payment, "telegram_payment_charge_id", None)
                 or getattr(payment, "provider_payment_charge_id", None))
    if not charge_id:
        # PAY-008: the fallback id MUST be unique per payment. The old hash used
        # only (user, payload, amount, currency), so two identical purchases by
        # the same user collided into one external_id and the second was deduped
        # away (lost). Include the message id + date, which are unique per payment.
        uniq = (
            f"{user_id}:{payment.invoice_payload}:{payment.total_amount}:"
            f"{payment.currency}:{message.message_id}:{getattr(message, 'date', '')}"
        )
        charge_id = "fallback_" + hashlib.sha256(uniq.encode()).hexdigest()[:32]
        logger.warning(f"No telegram_payment_charge_id; using unique fallback for user {user_id}")

    engine_plan = _plan_to_engine(plan_key)
    duration_days = plan.get("duration_days", 30)
    # XTR total_amount is the whole number of Stars — no // 100 (see pricing.py).
    stars_received = payment.total_amount

    logger.info(
        f"payment_received user={user_id} plan={plan_key} charge_id={charge_id} "
        f"amount={payment.total_amount}{payment.currency}"
    )

    # ── Activate via Postgres (atomic, idempotent), resilient to Engine outages ──
    result = await _activate_with_resilience(
        user_id=user_id, engine_plan=engine_plan, provider="telegram_stars",
        charge_id=charge_id, duration_days=duration_days, plan_key=plan_key,
        amount_stars=stars_received,
        checkout_reference=checkout_reference,
    )

    # Best-effort revenue metrics — must NEVER gate or fail the activation.
    try:
        if redis_client:
            redis_client.incrbyfloat("revenue_stars", stars_received)
            redis_client.incrbyfloat(f"revenue_{plan_key}", stars_received)
    except Exception as e:
        logger.debug(f"revenue metric skipped: {e}")

    # ── Always reply reassuringly. The user paid; never imply failure. ──
    if result.get("ok"):
        if result.get("already_processed"):
            await message.reply(
                f"✅ <b>You're all set!</b>\n\n"
                f"This payment was already applied — your <b>{plan['name']}</b> is active.",
                parse_mode="HTML",
            )
        else:
            await message.reply(_success_message(plan), parse_mode="HTML")
        logger.info(
            f"payment_activated user={user_id} plan={plan_key} stars={stars_received} "
            f"already={result.get('already_processed')}"
        )
    else:
        # Engine was unreachable but we durably queued the activation — it will
        # complete within minutes. Do not tell the user it failed.
        await message.reply(
            f"✅ <b>Payment received — thank you!</b>\n\n"
            f"Your <b>{plan['name']}</b> is being activated and will be live within a few minutes.\n"
            f"If anything looks off after 10 minutes, contact @TonGPT_Support with "
            f"User ID <code>{user_id}</code>.",
            parse_mode="HTML",
        )
        logger.error(
            f"payment_activation_deferred user={user_id} plan={plan_key} "
            f"charge_id={charge_id} queued={result.get('queued')} error={result.get('error')}"
        )

# TON Payment Handler
@router.callback_query(lambda c: c.data == "pay_ton")
async def handle_ton_payment(callback_query: types.CallbackQuery):
    """Handle the 'TON Payment' button.

    Delegates to the automated, memo-based TON flow in
    handlers/ton_payment_handler.py. That module shows the plan picker, the exact
    amount + address + memo + QR, and a background monitor activates the
    subscription automatically once the transfer confirms on-chain. If the TON
    path is not yet enabled/configured, the user is told to use Telegram Stars.
    """
    from handlers.ton_payment_handler import show_plan_selection
    await show_plan_selection(callback_query)

# Other callback handlers (referrals, status, etc.)
@router.callback_query(lambda c: c.data == "referrals")
async def referrals_callback(callback_query: types.CallbackQuery):
    """Handle referrals callback"""
    user_id = callback_query.from_user.id
    referral_link = f"https://t.me/TonGptt_bot?start={user_id}"
    
    # Get VERIFIED referral count from Redis (only counts validated referrals)
    referral_count = await get_referral_count(user_id)
    next_reward = get_next_referral_reward(referral_count)
    
    msg = (
        f"🎁 <b>Referral Program</b>\n\n"
        f"💰 <b>Earn Free Access:</b>\n"
        f"• 5 verified referrals = Starter Plan (30 days)\n"
        f"• 10 verified referrals = Pro Plan (30 days)\n"
        f"• 25 verified referrals = Elite Plan (30 days)\n\n"
        f"🔗 <b>Your Referral Link:</b>\n"
        f"<code>{referral_link}</code>\n\n"
        f"📊 <b>Current Status:</b>\n"
        f"• Verified Referrals: {referral_count}\n"
        f"• Next reward: {next_reward}\n\n"
        f"📈 <b>How it works:</b>\n"
        f"1. Share your link with friends\n"
        f"2. They join and use the bot\n"
        f"3. Referral counts after 24h + 3 commands\n"
        f"4. Get automatic plan upgrades"
    )
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅️ Back", callback_data="back_to_payment")]
    ])
    
    await callback_query.message.edit_text(msg, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(lambda c: c.data.startswith("check_status_"))
async def check_status_callback(callback_query: types.CallbackQuery):
    """Check user subscription status"""
    user_id = callback_query.from_user.id
    
    # Get user plan and usage from Redis
    current_plan = await get_user_plan(user_id)
    usage_today = await get_daily_usage(user_id)
    plan_details = await get_plan_details(user_id)
    
    msg = (
        f"📊 <b>Account Status</b>\n\n"
        f"👤 <b>User ID:</b> {user_id}\n"
        f"📋 <b>Current Plan:</b> {current_plan}\n"
        f"📅 <b>Expires:</b> {plan_details.get('expires', 'N/A')}\n"
        f"🔢 <b>Queries Today:</b> {usage_today}/{plan_details.get('daily_limit', '10')}\n"
        f"🐋 <b>Whale Threshold:</b> >{plan_details.get('whale_threshold', '∞')} TON\n\n"
        f"🎯 <b>Active Features:</b>\n"
    )
    
    for feature in plan_details.get('features', ['Basic token scanning', 'Limited AI responses']):
        msg += f"• {feature}\n"
    
    if current_plan == "Free":
        msg += (
            f"\n🚀 <b>Upgrade Benefits:</b>\n"
            f"• More daily queries\n"
            f"• Advanced whale alerts\n"
            f"• Priority support\n"
            f"• Real-time data\n\n"
            f"💡 Upgrade with Telegram Stars for instant activation!"
        )
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅️ Back", callback_data="back_to_payment")]
    ])
    
    await callback_query.message.edit_text(msg, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(lambda c: c.data == "plan_details")
async def plan_details_callback(callback_query: types.CallbackQuery):
    """Show detailed plan comparison"""
    
    msg = (
        f"📋 <b>Detailed Plan Comparison</b>\n\n"
        f"🆓 <b>Free Tier</b>\n"
        f"• 10 AI queries/day\n"
        f"• Basic /scan command\n"
        f"• Community access\n\n"
    )
    
    for plan_key, plan in PLANS.items():
        emoji = {"starter": "🥉", "pro": "🥈", "pro_plus": "🥇", "elite": "💎"}.get(plan_key, "📦")
        queries = "Unlimited" if plan['queries_per_day'] == -1 else f"{plan['queries_per_day']}"
        
        msg += (
            f"{emoji} <b>{plan['name']}</b> - {plan['price_stars']}⭐ or {plan['price_ton']}🪙\n"
            f"• {queries} queries/day\n"
            f"• Whale alerts >{plan['whale_threshold']} TON\n"
        )
        
        for feature in plan['features'][:2]:
            msg += f"• {feature}\n"
        msg += "\n"
    
    msg += f"💡 All premium plans include exclusive alpha groups and priority support!"
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅️ Back to Payment", callback_data="back_to_payment")]
    ])
    
    await callback_query.message.edit_text(msg, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(lambda c: c.data == "back_to_payment")
async def back_to_payment_callback(callback_query: types.CallbackQuery):
    """Go back to main payment screen"""
    user_id = callback_query.from_user.id
    user_name = callback_query.from_user.first_name or "User"

    # Check current user status
    current_plan = await get_user_plan(user_id)

    payment_menu_text = (
        f"💎 <b>TonGPT Premium Plans</b>\n\n"
        f"👤 <b>User:</b> {user_name} (ID: {user_id})\n"
        f"📋 <b>Current Plan:</b> {current_plan}\n\n"
        f"🌟 <b>Payment via Telegram Stars</b>\n"
        f"💰 Easy, instant, and secure!\n\n"
        f"📦 <b>Available Plans:</b>\n"
    )

    # Add plan details
    for plan_key, plan in PLANS.items():
        features_text = "\n".join([f"  • {feature}" for feature in plan["features"][:3]])
        payment_menu_text += (
            f"\n🎯 <b>{plan['name']}</b> - {plan['price_stars']} ⭐\n"
            f"{features_text}\n"
        )

    payment_menu_text += (
        f"\n💳 <b>Payment Methods:</b>\n"
        f"⭐ Telegram Stars (instant)\n"
        f"🪙 TON Wallet (manual)\n"
        f"💎 Crypto payments (manual)\n\n"
        f"🎁 <b>Special:</b> Use /refer to earn free access!"
    )

    # Inline keyboard with payment options (prices rendered from core/pricing.py).
    payment_keyboard = _build_payment_keyboard(user_id)

    await callback_query.message.edit_text(
        payment_menu_text,
        parse_mode="HTML",
        reply_markup=payment_keyboard,
    )

# Helper functions
async def get_user_plan(user_id: int) -> str:
    """Get current user plan from C# Engine"""
    try:
        status = await engine_client.get_user_status(str(user_id))
        return status.get("plan", "Free").title()
    except Exception as e:
        logger.error(f"Error getting plan from engine: {e}")
        return "Free"

async def get_daily_usage(user_id: int) -> int:
    """Get daily usage count"""
    # Usage tracking might still be in Redis for speed, or moved to C# later
    # For now, keep as is or fetch from C# if C# tracks usage
    try:
        usage = redis_client.get(f"usage_today:{user_id}")
        return int(usage) if usage else 0
    except:
        return 0

async def get_referral_count(user_id: int) -> int:
    """Get referral count from Redis"""
    try:
        count = redis_client.get(f"referrals:{user_id}")
        return int(count) if count else 0
    except:
        return 0

# Engine plan names -> canonical pricing keys ("ProPlus" was previously missed
# because .lower() gives "proplus", not "pro_plus" — paid Pro+ users were shown
# the Free fallback).
_ENGINE_PLAN_TO_KEY = {
    "starter": "starter",
    "pro": "pro",
    "proplus": "pro_plus",
    "pro_plus": "pro_plus",
    "pro+": "pro_plus",
    "elite": "elite",
}


async def get_plan_details(user_id: int) -> dict:
    """Get detailed plan information.

    PAY-014: expiry is sourced from the Engine's get_user_status (the actual
    activation authority), NOT a Redis TTL the activation flow never set.
    LIMIT-INCONSISTENCY-001: the Free daily limit shows the rate limiter's real
    cap (RATE_LIMIT_FREE_PER_DAY) instead of a hardcoded '10'.
    """
    expires = "N/A"
    plan_raw = "Free"
    try:
        status = await engine_client.get_user_status(str(user_id))
        plan_raw = status.get("plan", "Free")
        expiry = status.get("expiry")
        if expiry:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(str(expiry).replace('Z', '+00:00'))
            days_left = (dt - datetime.now(timezone.utc)).days
            expires = f"{max(days_left, 0)} days ({dt.strftime('%Y-%m-%d')})"
    except Exception as e:
        logger.error(f"Error getting plan details from engine: {e}")

    key = _ENGINE_PLAN_TO_KEY.get((plan_raw or "").strip().lower())
    if key:
        plan = PLANS[key]
        return {
            'daily_limit': plan['queries_per_day'] if plan['queries_per_day'] != -1 else "Unlimited",
            'whale_threshold': plan['whale_threshold'],
            'features': plan['features'],
            'expires': expires
        }

    try:
        free_daily = int(os.getenv("RATE_LIMIT_FREE_PER_DAY", "25"))
    except ValueError:
        free_daily = 25
    return {
        'daily_limit': str(free_daily),
        'whale_threshold': '∞',
        'features': ['Basic token scanning', 'Limited AI responses', 'Community access'],
        'expires': 'N/A'
    }

def get_next_referral_reward(count: int) -> str:
    """Get next referral reward milestone"""
    if count < 5:
        return f"Starter Plan ({5-count} more referrals)"
    elif count < 10:
        return f"Pro Plan ({10-count} more referrals)"
    elif count < 25:
        return f"Elite Plan ({25-count} more referrals)"
    else:
        return "All rewards unlocked!"

def _plan_to_engine(plan_key: str) -> str:
    """Map Python plan key to C# SubscriptionPlan enum name."""
    return {"starter": "Starter", "pro": "Pro", "pro_plus": "ProPlus", "elite": "Elite"}.get(plan_key, plan_key)


# NOTE: activate_premium_plan() was REMOVED — it used the deleted, amount-blind
# /Subscription/upgrade path. Activation now flows ONLY through the
# successful_payment handler -> _activate_with_resilience -> complete_payment.
