from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import LabeledPrice, PreCheckoutQuery, Message
import logging
import os
import logging
import os
from services.engine_client import engine_client
from utils.redis_conn import redis_client

logger = logging.getLogger(__name__)
router = Router()

# Payment configuration
PAYMENT_TOKEN = os.getenv("PAYMENT_TOKEN")

# Plan configurations with Telegram Stars pricing
PLANS = {
    "starter": {
        "name": "Starter Plan",
        "price_ton": 30,
        "price_stars": 100,  # 100 Telegram Stars
        "duration_days": 30,
        "features": [
            "100 AI queries per day",
            "Basic market alerts",
            "Standard response speed",
            "Email support"
        ],
        "queries_per_day": 100,
        "whale_threshold": 100
    },
    "pro": {
        "name": "Pro Plan", 
        "price_ton": 130,
        "price_stars": 400,  # 400 Telegram Stars
        "duration_days": 30,
        "features": [
            "500 AI queries per day",
            "Advanced whale alerts",
            "Priority support", 
            "Custom notifications",
            "Portfolio tracking"
        ],
        "queries_per_day": 500,
        "whale_threshold": 50
    },
    "pro_plus": {
        "name": "Pro+ Plan",
        "price_ton": 200,
        "price_stars": 600,  # 600 Telegram Stars  
        "duration_days": 30,
        "features": [
            "1000 AI queries per day",
            "Real-time market data",
            "Advanced analytics",
            "API access (100 calls/day)",
            "Advanced charts"
        ],
        "queries_per_day": 1000,
        "whale_threshold": 25
    },
    "elite": {
        "name": "Elite Plan",
        "price_ton": 300,
        "price_stars": 1000,  # 1000 Telegram Stars
        "duration_days": 30,
        "features": [
            "Unlimited AI queries",
            "VIP whale alerts",
            "Custom API access", 
            "Direct developer support",
            "1-on-1 support calls"
        ],
        "queries_per_day": -1,  # Unlimited
        "whale_threshold": 10
    }
}

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
    
    # Inline keyboard with payment options
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="🥉 Starter - 100⭐", callback_data="pay_stars_starter"),
            types.InlineKeyboardButton(text="🥈 Pro - 400⭐", callback_data="pay_stars_pro")
        ],
        [
            types.InlineKeyboardButton(text="🥇 Pro+ - 600⭐", callback_data="pay_stars_pro_plus"),
            types.InlineKeyboardButton(text="💎 Elite - 1000⭐", callback_data="pay_stars_elite")
        ],
        [
            types.InlineKeyboardButton(text="🪙 TON Payment", callback_data="pay_ton"),
            types.InlineKeyboardButton(text="ℹ️ Plan Details", callback_data="plan_details")
        ],
        [
            types.InlineKeyboardButton(text="🎁 Referrals", callback_data="referrals"),
            types.InlineKeyboardButton(text="📊 Check Status", callback_data=f"check_status_{user_id}")
        ]
    ])
    
    await message.reply(payment_msg, parse_mode="HTML", reply_markup=keyboard)

# Telegram Stars Payment Handlers
@router.callback_query(lambda c: c.data.startswith("pay_stars_"))
async def handle_stars_payment(callback_query: types.CallbackQuery):
    """Handle Telegram Stars payment"""
    if not PAYMENT_TOKEN:
        await callback_query.answer("Payment not configured", show_alert=True)
        return
    
    plan_key = callback_query.data.split("pay_stars_")[-1]
    plan = PLANS.get(plan_key)
    
    if not plan:
        await callback_query.answer("Invalid plan", show_alert=True)
        return
    
    # Create invoice
    prices = [LabeledPrice(label=f"{plan['name']} (1 month)", amount=plan['price_stars'] * 100)]
    
    await callback_query.bot.send_invoice(
        chat_id=callback_query.message.chat.id,
        title=f"TonGPT {plan['name']}",
        description=f"Upgrade to {plan['name']} for premium features:\n" + 
                   "\n".join([f"• {feature}" for feature in plan['features']]),
        payload=f"premium_{plan_key}",
        provider_token=PAYMENT_TOKEN,
        currency="XTR",  # Telegram Stars
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
    
    if payload.startswith("premium_"):
        plan_key = payload.split("premium_")[-1]
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
    
    if payment.invoice_payload.startswith("premium_"):
        plan_key = payment.invoice_payload.split("premium_")[-1]
        plan = PLANS.get(plan_key)
        
        if plan:
            # Activate premium subscription
            await activate_premium_plan(user_id, plan_key, plan)
            
            # Track revenue
            stars_received = payment.total_amount // 100
            redis_client.incrbyfloat("revenue_stars", stars_received)
            redis_client.incrbyfloat(f"revenue_{plan_key}", stars_received)
            
            # Send confirmation
            confirmation_msg = (
                f"✅ <b>Payment Successful!</b>\n\n"
                f"🎯 <b>Plan:</b> {plan['name']}\n"
                f"⏱️ <b>Duration:</b> {plan['duration_days']} days\n"
                f"💫 <b>Paid:</b> {stars_received} Telegram Stars\n\n"
                f"🚀 <b>Your new features:</b>\n"
            )
            
            for feature in plan['features']:
                confirmation_msg += f"• {feature}\n"
            
            confirmation_msg += (
                f"\n💡 <b>Try these commands:</b>\n"
                f"/scan - Enhanced token analysis\n"
                f"/whale - Premium whale alerts\n"
                f"/portfolio - Track your holdings\n"
                f"/status - Check your subscription\n\n"
                f"🎉 Welcome to TonGPT Premium!"
            )
            
            await message.reply(confirmation_msg, parse_mode="HTML")
            
            # Log the successful payment
            logger.info(f"Premium activated: User {user_id}, Plan {plan_key}, Stars {stars_received}")

# TON Payment Handler
@router.callback_query(lambda c: c.data == "pay_ton")
async def handle_ton_payment(callback_query: types.CallbackQuery):
    """Handle TON payment option"""
    user_id = callback_query.from_user.id
    
    ton_payment_msg = (
        f"🪙 <b>TON Payment Options</b>\n\n"
        f"📋 <b>Manual TON Payment Plans:</b>\n\n"
    )
    
    for plan_key, plan in PLANS.items():
        ton_payment_msg += (
            f"🎯 <b>{plan['name']}</b> - {plan['price_ton']} TON\n"
            f"  • {plan['queries_per_day']} queries/day {'(unlimited)' if plan['queries_per_day'] == -1 else ''}\n"
            f"  • Whale alerts >{plan['whale_threshold']} TON\n\n"
        )
    
    ton_payment_msg += (
        f"💳 <b>Payment Process:</b>\n"
        f"1. Contact @TonGPT_Support\n"
        f"2. Send your plan choice + user ID: {user_id}\n"
        f"3. Get payment wallet address\n"
        f"4. Send TON and get instant activation\n\n"
        f"⚡ <b>Why choose TON payment?</b>\n"
        f"• Direct blockchain transaction\n"
        f"• Lower fees than traditional payment\n"
        f"• Support the TON ecosystem\n"
        f"• Get exclusive TON holder benefits"
    )
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💬 Contact Support", url="https://t.me/TonGPT_Support")],
        [types.InlineKeyboardButton(text="⬅️ Back", callback_data="back_to_payment")]
    ])
    
    await callback_query.message.edit_text(ton_payment_msg, parse_mode="HTML", reply_markup=keyboard)

# Other callback handlers (referrals, status, etc.)
@router.callback_query(lambda c: c.data == "referrals")
async def referrals_callback(callback_query: types.CallbackQuery):
    """Handle referrals callback"""
    user_id = callback_query.from_user.id
    referral_link = f"https://t.me/TonGptt_bot?start={user_id}"
    
    # Get referral count from Redis
    referral_count = await get_referral_count(user_id)
    next_reward = get_next_referral_reward(referral_count)
    
    msg = (
        f"🎁 <b>Referral Program</b>\n\n"
        f"💰 <b>Earn Free Access:</b>\n"
        f"• 5 referrals = Starter Plan (30 days)\n"
        f"• 10 referrals = Pro Plan (30 days)\n"
        f"• 25 referrals = Elite Plan (30 days)\n\n"
        f"🔗 <b>Your Referral Link:</b>\n"
        f"<code>{referral_link}</code>\n\n"
        f"📊 <b>Current Status:</b>\n"
        f"• Referrals: {referral_count}\n"
        f"• Next reward: {next_reward}\n\n"
        f"📈 <b>How it works:</b>\n"
        f"1. Share your link with friends\n"
        f"2. They join and use the bot\n"
        f"3. Get automatic plan upgrades"
    )
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⬅️ Back", callback_data="back_to_payment")]
    ])
    
    await callback_query.message.edit_text(msg, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(lambda c: c.data.startswith("check_status_"))
async def check_status_callback(callback_query: types.CallbackQuery):
    """Check user subscription status"""
    user_id = int(callback_query.data.split("_")[-1])
    
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
    # Simulate the pay command
    await pay_command(callback_query.message)

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

async def get_plan_details(user_id: int) -> dict:
    """Get detailed plan information"""
    current_plan = await get_user_plan(user_id)
    
    if current_plan.lower() in PLANS:
        plan = PLANS[current_plan.lower()]
        
        # Get expiration date
        try:
            ttl = redis_client.ttl(f"premium:{user_id}")
            expires = f"{ttl // 86400} days" if ttl > 0 else "N/A"
        except:
            expires = "N/A"
            
        return {
            'daily_limit': plan['queries_per_day'] if plan['queries_per_day'] != -1 else "Unlimited",
            'whale_threshold': plan['whale_threshold'],
            'features': plan['features'],
            'expires': expires
        }
    
    return {
        'daily_limit': '10',
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

async def activate_premium_plan(user_id: int, plan_key: str, plan: dict):
    """Activate premium plan for user via C# Engine"""
    try:
        # Call C# Engine to upgrade user
        success = await engine_client.upgrade_user(str(user_id), plan_key)
        
        if success:
            logger.info(f"Successfully activated {plan_key} for {user_id} via Engine")
        else:
            logger.error(f"Failed to activate {plan_key} for {user_id} via Engine")

        # Keep some local Redis setting for fallback/speed if needed, but Engine is source of truth
        # For now, we trust the Engine call.
        
        # Reset daily usage in Redis (still managed by Python for now)
        redis_client.delete(f"usage_today:{user_id}")
        
    except Exception as e:
        logger.error(f"Error activating plan: {e}")

# Registration function
def register_pay_handlers(dp):
    """Register payment handlers with the dispatcher"""
    dp.include_router(router)