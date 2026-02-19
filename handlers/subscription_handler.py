from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta
import logging
from typing import Optional
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)

from services.engine_client import engine_client

router = Router()

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
@router.message(Command("upgrade"))
async def start_upgrade(message: types.Message, state: FSMContext):
    """Start subscription upgrade process"""
    # Using the same callbacks as pay.py to unify the flow
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🥉 Starter - 100⭐", callback_data="pay_stars_starter")],
        [types.InlineKeyboardButton(text="🥈 Pro - 400⭐", callback_data="pay_stars_pro")],
        [types.InlineKeyboardButton(text="🥇 Pro+ - 600⭐", callback_data="pay_stars_pro_plus")],
        [types.InlineKeyboardButton(text="🪙 TON Payment", callback_data="pay_ton")]
    ])
    
    await message.reply(
        "🚀 <b>Upgrade Your Plan</b>\n\n"
        "Choose a plan to upgrade instantly using Telegram Stars or TON:\n\n"
        "🥉 <b>Starter</b>: 100 queries/day\n"
        "🥈 <b>Pro</b>: 500 queries/day + Alerts\n"
        "🥇 <b>Pro+</b>: 1000 queries/day + Analytics\n\n"
        "👇 <b>Select an option:</b>",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    # We don't need to set state here as pay.py handles the callbacks gracefully without state
    # await state.set_state(SubscriptionStates.choosing_tier)

def register_subscription_handlers(dp, config, redis_client):
    """Register subscription handlers"""
    # Redis client passed but handled via Engine mostly now
    dp.include_router(router)
    logger.info("✅ Subscription handlers registered (Hybrid Mode)")