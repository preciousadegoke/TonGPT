from aiogram import Router, types
from aiogram.filters import Command
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

from services.engine_client import engine_client
from core.config import load_config
from core.pricing import PLANS, PLAN_ORDER  # canonical single source of truth for prices

config = load_config()

router = Router()

# Display emoji per tier (presentation only — never a source of price data).
_PLAN_EMOJI = {"starter": "🥉", "pro": "🥈", "pro_plus": "🥇", "elite": "💎"}

# Plan configuration (Display only)
TIER_PRICES = {
    "Basic": 5.0,
    "Premium": 15.0
}

TIER_LIMITS = {
    "Free": 100,
    "Basic": 1000,
    "Premium": 10000
}

@router.message(Command("subscription", "sub"))
async def subscription_status(message: types.Message):
    """Show user subscription status via C# Engine"""
    user_id = message.from_user.id
    
    try:
        user_status = await engine_client.get_user_status(str(user_id))
        plan = user_status.get("plan", "Free").title()
        expiry = user_status.get("expiry")
        
        # Determine credits based on Plan (using static definitions for now)
        credits_remaining = TIER_LIMITS.get(plan, 100) # Default/Free
        
        status_text = (
            f"💎 <b>Your Subscription</b>\n\n"
            f"📋 Plan: <b>{plan}</b>\n"
            f"⚡ Credits: <b>{credits_remaining}</b> (Daily)\n"
        )
        
        if expiry:
            # Parse expiry date for display
            try:
                # C# returns ISO 8601
                dt = datetime.fromisoformat(expiry.replace('Z', '+00:00'))
                expiry_str = dt.strftime('%Y-%m-%d')
                status_text += f"📅 Expires: <b>{expiry_str}</b>\n"
            except:
                status_text += f"📅 Expires: <b>{expiry}</b>\n"
        
        if plan == "Free":
            status_text += f"\n🚀 <b>Upgrade for more features:</b>\n"
            status_text += f"• Basic: {TIER_PRICES['Basic']} TON/month\n"
            status_text += f"• Premium: {TIER_PRICES['Premium']} TON/month\n"
            status_text += f"\nUse /upgrade to upgrade your plan"
        
        await message.reply(status_text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Failed to check subscription: {e}")
        await message.reply("Could not retrieve subscription status. Please try again later.")

@router.message(Command("connect"))
async def connect_wallet(message: types.Message):
    """Guide user to connect wallet via MiniApp"""
    # Create button to open MiniApp
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text="🔌 Connect Wallet", 
            web_app=types.WebAppInfo(url=f"{config.get('MINIAPP_URL', 'https://t.me/TonGPT_Bot/app')}")
        )]
    ])
    
    await message.reply(
        "🔗 <b>Connect your TON Wallet</b>\n\n"
        "To subscribe to premium plans, you need to connect your wallet.\n"
        "Tap the button below to open the app and connect securely.",
        parse_mode="HTML",
        reply_markup=keyboard
    )


@router.message(Command("upgrade"))
async def start_upgrade(message: types.Message, **kwargs):
    """Start subscription upgrade — a single message listing all plans.

    Every price is rendered from core/pricing.py (the single source of truth) so
    the displayed amount ALWAYS equals what pay.py charges. Never hardcode prices
    here. The pay_stars_/pay_ton buttons are handled by handlers/pay.py.
    """
    # Plan buttons (2 per row), Star prices straight from PLANS.
    plan_btns = [
        types.InlineKeyboardButton(
            text=f"{_PLAN_EMOJI.get(k, '📦')} {PLANS[k]['name'].replace(' Plan', '')} - {PLANS[k]['price_stars']}⭐",
            callback_data=f"pay_stars_{k}",
        )
        for k in PLAN_ORDER
    ]
    rows = [plan_btns[i:i + 2] for i in range(0, len(plan_btns), 2)]
    rows.append([
        types.InlineKeyboardButton(text="🪙 TON Payment", callback_data="pay_ton"),
        types.InlineKeyboardButton(text="ℹ️ Plan Details", callback_data="plan_details"),
    ])
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=rows)

    lines = [
        "🚀 <b>Upgrade Your Plan</b>\n",
        "Choose a plan to upgrade instantly using Telegram Stars or TON:\n",
    ]
    for k in PLAN_ORDER:
        p = PLANS[k]
        qpd = "Unlimited queries/day" if p["queries_per_day"] == -1 else f"{p['queries_per_day']} queries/day"
        name = p["name"].replace(" Plan", "")
        lines.append(
            f"{_PLAN_EMOJI.get(k, '📦')} <b>{name}</b> ({p['price_stars']}⭐ / {p['price_ton']} TON): {qpd}"
        )
    lines.append("\n👇 <b>Select an option:</b>")

    await message.reply("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)

def register_subscription_handlers(dp, config=None, redis_client=None):
    """Register subscription handlers"""
    # Redis client passed but handled via Engine mostly now
    dp.include_router(router)
    logger.info("✅ Subscription handlers registered (Hybrid Mode)")