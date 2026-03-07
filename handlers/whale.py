# handlers/whale.py
from aiogram import Router, types
from aiogram.filters import Command
from services.tonapi import get_large_transactions, get_whale_summary
from utils.redis_conn import redis_client
from services.engine_client import engine_client
import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)
router = Router()


async def get_user_premium_status(redis_client, engine_client, user_id: int) -> bool:
    cached = redis_client.get(f"premium:{user_id}")
    if cached is not None:
        return cached == "1" or cached == b"1"
    try:
        status = await engine_client.get_user_status(str(user_id))
        plan = (status.get("plan") or "").lower()
        is_premium = plan not in ("", "free")
    except Exception:
        return False  # Fail closed — deny premium on Engine failure
    redis_client.set(
        f"premium:{user_id}", "1" if is_premium else "0", ex=300
    )
    return is_premium

# Whale configuration
WHALE_EMOJIS = {
    'small_whale': '🟡',
    'medium_whale': '🟠', 
    'large_whale': '🔴',
    'mega_whale': '🚨',
    'regular': '⚪'
}

WHALE_NAMES = {
    'small_whale': 'Small Whale',
    'medium_whale': 'Medium Whale',
    'large_whale': 'Large Whale', 
    'mega_whale': 'Mega Whale',
    'regular': 'Regular'
}

WHALE_THRESHOLDS = {
    'small_whale': 1000,    # 1K+ TON
    'medium_whale': 10000,  # 10K+ TON
    'large_whale': 100000,  # 100K+ TON
    'mega_whale': 1000000   # 1M+ TON
}

@router.message(Command("whale"))
async def whale_alerts(message: types.Message):
    """Show recent whale transactions and alerts"""
    user_id = message.from_user.id
    has_premium = await get_user_premium_status(redis_client, engine_client, user_id)
    # Get user plan or default to free
    status = await engine_client.get_user_status(str(user_id))
    user_plan = (status.get("plan") or "Free").lower()
    
    await message.reply("🐋 <b>Scanning for whale movements...</b>", parse_mode="HTML")
    await message.bot.send_chat_action(message.chat.id, "typing")
    
    try:
        # Determine limits based on user plan
        display_limit = get_display_limit_for_plan(user_plan)
        min_amount = get_whale_threshold_for_plan(user_plan)
        
        # Get large transactions
        transactions = await get_large_transactions(limit=20, min_amount=min_amount)
        
        if not transactions:
            no_data_msg = format_no_whale_data_message(user_plan, min_amount, has_premium)
            await message.reply(no_data_msg, parse_mode="HTML")
            return
        
        # Format whale alerts response
        response_msg = await format_whale_alerts_response(
            transactions[:display_limit], 
            user_plan, 
            has_premium, 
            display_limit
        )
        
        # Add action buttons
        keyboard = create_whale_action_keyboard(has_premium, user_plan)
        
        await message.reply(response_msg, parse_mode="HTML", reply_markup=keyboard)
        
        # Track usage for premium users
        if has_premium:
            redis_client.incr(f"whale_usage:{user_id}")
            logger.info(f"Whale alerts accessed by premium user {user_id} ({user_plan})")
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Whale alert error for user {user_id}: {error_msg}")
        
        await message.reply(
            f"⚠️ <b>Whale Alert System Unavailable</b>\n\n"
            f"🔧 <b>Service Status:</b> Temporary error\n"
            f"🔄 <b>Action:</b> Please try again in a few moments\n\n"
            f"💡 <b>Alternative Options:</b>\n"
            f"• Use /transactions &lt;address&gt; for specific wallets\n"
            f"• Check /status for system health\n"
            f"• Use /scan for token analysis\n\n"
            f"🛠️ <b>Error Details:</b> <code>{error_msg[:80]}...</code>",
            parse_mode="HTML"
        )

@router.message(Command("whale_summary"))
async def whale_summary(message: types.Message):
    """Show detailed whale activity summary"""
    user_id = message.from_user.id
    
    # Check premium status
    has_premium = await get_user_premium_status(redis_client, engine_client, user_id)
    if not has_premium:
        await message.reply(
            "🐋 <b>Whale Activity Summary</b>\n\n"
            "❌ <b>Premium Feature Required</b>\n\n"
            "🔒 <b>Premium Summary Features:</b>\n"
            "• 24-hour whale activity overview\n"
            "• Volume and transaction breakdowns\n"
            "• Whale category distribution\n"
            "• Market impact analysis\n"
            "• Historical trend comparison\n\n"
            "💎 <b>Upgrade Options:</b>\n"
            "• /subscribe - Premium plans starting 100 ⭐\n"
            "• /refer - Earn free premium access\n\n"
            "🆓 <b>Free Alternative:</b> Use /whale for basic whale alerts",
            parse_mode="HTML"
        )
        return
    
    status = await engine_client.get_user_status(str(user_id))
    user_plan = (status.get("plan") or "Free").lower()
    
    await message.reply("📊 <b>Analyzing whale activity patterns...</b>", parse_mode="HTML")
    await message.bot.send_chat_action(message.chat.id, "typing")
    
    try:
        # Get summary data for different time periods
        summary_24h = await get_whale_summary(hours=24)
        summary_7d = None
        
        # Pro+ and Elite get 7-day data
        if user_plan in ['pro_plus', 'elite']:
            summary_7d = await get_whale_summary(hours=168)  # 7 days
        
        if not summary_24h or summary_24h.get('total_transactions', 0) == 0:
            await message.reply(
                f"📊 <b>WHALE ACTIVITY SUMMARY</b> - {user_plan.title()}\n\n"
                f"📈 <b>24 Hours:</b> No significant whale activity\n"
                f"📊 <b>Status:</b> Market is relatively quiet\n\n"
                f"🔍 <b>Monitoring Thresholds:</b>\n"
                f"• 🟡 Small Whale: {WHALE_THRESHOLDS['small_whale']:,}+ TON\n"
                f"• 🟠 Medium Whale: {WHALE_THRESHOLDS['medium_whale']:,}+ TON\n"
                f"• 🔴 Large Whale: {WHALE_THRESHOLDS['large_whale']:,}+ TON\n"
                f"• 🚨 Mega Whale: {WHALE_THRESHOLDS['mega_whale']:,}+ TON\n\n"
                f"⏰ Check back later for whale movement updates!",
                parse_mode="HTML"
            )
            return
        
        # Format comprehensive summary
        response_msg = await format_whale_summary_response(
            summary_24h, 
            summary_7d, 
            user_plan
        )
        
        # Add action buttons
        keyboard = create_summary_action_keyboard(user_plan)
        
        await message.reply(response_msg, parse_mode="HTML", reply_markup=keyboard)
        
        # Track usage
        redis_client.incr(f"whale_summary_usage:{user_id}")
        logger.info(f"Whale summary accessed by premium user {user_id} ({user_plan})")
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Whale summary error for user {user_id}: {error_msg}")
        
        await message.reply(
            f"⚠️ <b>Whale Summary Unavailable</b>\n\n"
            f"🔧 Could not generate whale activity summary.\n"
            f"Please try again in a few moments.\n\n"
            f"💡 <b>Alternative:</b> Use /whale for current alerts\n\n"
            f"🛠️ Error: <code>{error_msg[:80]}...</code>",
            parse_mode="HTML"
        )

@router.message(Command("whale_config"))
async def whale_config(message: types.Message):
    """Configure whale alert settings"""
    user_id = message.from_user.id
    
    # Check premium status
    has_premium = await get_user_premium_status(redis_client, engine_client, user_id)
    if not has_premium:
        await message.reply(
            "⚙️ <b>Whale Configuration</b>\n\n"
            "❌ Premium feature required for custom whale settings.\n\n"
            "🔒 <b>Premium Configuration Features:</b>\n"
            "• Custom alert thresholds\n"
            "• Notification preferences\n"
            "• Whale category filters\n"
            "• Auto-refresh intervals\n\n"
            "💎 Upgrade with /subscribe",
            parse_mode="HTML"
        )
        return
    
    status = await engine_client.get_user_status(str(user_id))
    user_plan = (status.get("plan") or "Free").lower()
    current_threshold = get_whale_threshold_for_plan(user_plan)
    
    config_msg = (
        f"⚙️ <b>WHALE ALERT CONFIGURATION</b> - {user_plan.title()}\n\n"
        f"🎯 <b>Current Settings:</b>\n"
        f"• Minimum Alert: <b>{current_threshold:,.0f} TON</b>\n"
        f"• Display Limit: <b>{get_display_limit_for_plan(user_plan)} transactions</b>\n"
        f"• Auto-refresh: <b>Enabled</b>\n"
        f"• Notifications: <b>{'Enabled' if redis_client.get(f'whale_notifications:{user_id}') else 'Disabled'}</b>\n\n"
        f"🎚️ <b>Available Thresholds:</b>\n"
        f"• 🟡 Small Whale: {WHALE_THRESHOLDS['small_whale']:,}+ TON\n"
        f"• 🟠 Medium Whale: {WHALE_THRESHOLDS['medium_whale']:,}+ TON\n"
        f"• 🔴 Large Whale: {WHALE_THRESHOLDS['large_whale']:,}+ TON\n"
        f"• 🚨 Mega Whale: {WHALE_THRESHOLDS['mega_whale']:,}+ TON\n\n"
        f"💡 Higher plans get access to lower thresholds"
    )
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="🔔 Toggle Notifications", callback_data=f"toggle_whale_notifications_{user_id}"),
        ],
        [
            types.InlineKeyboardButton(text="📊 Test Alerts", callback_data="test_whale_alerts"),
            types.InlineKeyboardButton(text="🔄 Refresh Config", callback_data="refresh_whale_config")
        ],
        [
            types.InlineKeyboardButton(text="⬅️ Back to Whale Alerts", callback_data="back_to_whale_alerts")
        ]
    ])
    
    await message.reply(config_msg, parse_mode="HTML", reply_markup=keyboard)

# Callback handlers
@router.callback_query(lambda c: c.data == "whale_refresh")
async def whale_refresh_callback(callback_query: types.CallbackQuery):
    """Refresh whale data"""
    await callback_query.answer("🔄 Refreshing whale data...")
    # Create a new message object with the callback query's message content
    new_message = types.Message(
        message_id=callback_query.message.message_id,
        from_user=callback_query.from_user,
        date=callback_query.message.date,
        chat=callback_query.message.chat,
        content_type='text',
        options={'text': '/whale'},
        bot=callback_query.bot
    )
    await whale_alerts(new_message)

@router.callback_query(lambda c: c.data == "whale_summary_24h")
async def whale_summary_callback(callback_query: types.CallbackQuery):
    """Show 24h whale summary"""
    await callback_query.answer("📊 Loading 24h summary...")
    new_message = types.Message(
        message_id=callback_query.message.message_id,
        from_user=callback_query.from_user,
        date=callback_query.message.date,
        chat=callback_query.message.chat,
        content_type='text',
        options={'text': '/whale_summary'},
        bot=callback_query.bot
    )
    await whale_summary(new_message)

@router.callback_query(lambda c: c.data == "whale_settings")
async def whale_settings_callback(callback_query: types.CallbackQuery):
    """Show whale alert settings"""
    user_id = callback_query.from_user.id
    has_premium = await get_user_premium_status(redis_client, engine_client, user_id)
    
    if not has_premium:
        await callback_query.answer("❌ Premium required for settings", show_alert=True)
        return
    
    status = await engine_client.get_user_status(str(user_id))
    current_plan = (status.get("plan") or "Free").lower()
    current_threshold = get_whale_threshold_for_plan(current_plan)
    
    settings_msg = (
        f"⚙️ <b>Whale Alert Settings</b>\n\n"
        f"🎯 <b>Current Threshold:</b> {current_threshold:,.0f} TON\n"
        f"🔔 <b>Notifications:</b> {'Enabled' if redis_client.get(f'whale_notifications:{user_id}') else 'Disabled'}\n"
        f"📱 <b>Auto-refresh:</b> Every 5 minutes\n"
        f"📊 <b>Display Limit:</b> {get_display_limit_for_plan(current_plan)} transactions\n\n"
        f"💡 Settings are based on your premium plan level"
    )
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="🔔 Toggle Notifications", callback_data=f"toggle_notifications_{user_id}"),
        ],
        [
            types.InlineKeyboardButton(text="⬅️ Back to Alerts", callback_data="whale_refresh")
        ]
    ])
    
    await callback_query.message.edit_text(settings_msg, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(lambda c: c.data.startswith("toggle_notifications_"))
async def toggle_notifications_callback(callback_query: types.CallbackQuery):
    """Toggle whale notifications"""
    user_id = callback_query.from_user.id
    
    current_status = redis_client.get(f"whale_notifications:{user_id}")
    
    if current_status:
        redis_client.delete(f"whale_notifications:{user_id}")
        await callback_query.answer("🔕 Whale notifications disabled", show_alert=True)
    else:
        redis_client.set(f"whale_notifications:{user_id}", "enabled")
        await callback_query.answer("🔔 Whale notifications enabled", show_alert=True)
    
    # Refresh the settings display
    await whale_settings_callback(callback_query)

# Helper functions
def get_whale_threshold_for_plan(plan: str) -> float:
    """Get minimum whale threshold based on user plan"""
    if isinstance(plan, bytes):
        plan = plan.decode('utf-8')
    
    thresholds = {
        'free': 50000.0,       # 50K TON
        'starter': 10000.0,    # 10K TON
        'pro': 5000.0,         # 5K TON
        'pro_plus': 1000.0,    # 1K TON
        'elite': 500.0         # 500 TON
    }
    
    return thresholds.get(plan, 50000.0)

def get_display_limit_for_plan(plan: str) -> int:
    """Get display limit based on user plan"""
    if isinstance(plan, bytes):
        plan = plan.decode('utf-8')
    
    limits = {
        'free': 3,
        'starter': 5,
        'pro': 8,
        'pro_plus': 12,
        'elite': 15
    }
    
    return limits.get(plan, 3)

def format_no_whale_data_message(user_plan: str, min_amount: float, has_premium: bool) -> str:
    """Format message when no whale data is available"""
    base_msg = f"🐋 <b>WHALE ALERT SYSTEM</b> - {user_plan.title()}\n\n"
    base_msg += f"📊 <b>Current Status:</b> No major movements detected\n\n"
    base_msg += f"🔍 <b>Monitoring Transactions ≥ {min_amount:,.0f} TON</b>\n\n"
    
    base_msg += f"⚡ <b>Detection Thresholds:</b>\n"
    for category, threshold in WHALE_THRESHOLDS.items():
        emoji = WHALE_EMOJIS[category]
        name = WHALE_NAMES[category]
        base_msg += f"• {emoji} {name}: {threshold:,}+ TON\n"
    
    if has_premium:
        base_msg += f"\n💡 Use /whale_summary for detailed analytics"
    else:
        base_msg += f"\n💡 Upgrade to Premium for lower thresholds and more features"
    
    return base_msg

async def format_whale_alerts_response(transactions: List[Dict], user_plan: str, has_premium: bool, display_limit: int) -> str:
    """Format whale alerts response message"""
    msg = f"🐋 <b>WHALE MOVEMENTS DETECTED</b> - {user_plan.title()}\n\n"
    
    total_volume = 0
    total_usd = 0
    
    for i, tx in enumerate(transactions, 1):
        # Get transaction details
        amount_ton = tx.get('amount_ton', 0)
        usd_value = tx.get('usd_value', 0)
        whale_category = classify_whale_transaction(amount_ton)
        
        # Get display elements
        emoji = WHALE_EMOJIS.get(whale_category, '⚪')
        whale_name = WHALE_NAMES.get(whale_category, 'Regular')
        
        # Format addresses
        from_addr = format_address(tx.get('from_address', 'unknown'))
        to_addr = format_address(tx.get('to_address', 'unknown'))
        
        # Format timestamp
        timestamp = tx.get('timestamp', 0)
        time_str = format_timestamp(timestamp)
        
        # Transaction type
        tx_type = tx.get('type', 'transfer').replace('_', ' ').title()
        
        msg += (
            f"{emoji} <b>{whale_name}</b> #{i}\n"
            f"💰 <b>{amount_ton:,.0f} TON</b> (~${usd_value:,.0f})\n"
            f"📤 <code>{from_addr}</code>\n"
            f"📥 <code>{to_addr}</code>\n"
            f"🕐 {time_str} | 🔗 {tx_type}\n\n"
        )
        
        total_volume += amount_ton
        total_usd += usd_value
    
    # Add summary stats
    msg += (
        f"📊 <b>Summary ({len(transactions)} transactions):</b>\n"
        f"💎 Total Volume: <b>{total_volume:,.0f} TON</b>\n"
        f"💵 USD Value: <b>${total_usd:,.0f}</b>\n\n"
    )
    
    if has_premium:
        msg += f"🔄 Auto-refresh enabled | 📈 Use /whale_summary for analytics"
    else:
        msg += f"💎 Upgrade to Premium for more detailed analysis and alerts"
    
    return msg

async def format_whale_summary_response(summary_24h: Dict, summary_7d: Optional[Dict], user_plan: str) -> str:
    """Format whale summary response message"""
    msg = f"📊 <b>WHALE ACTIVITY ANALYTICS</b> - {user_plan.title()}\n\n"
    
    # 24h Summary
    msg += "📈 <b>Last 24 Hours:</b>\n"
    msg += format_period_summary(summary_24h, "24h")
    
    # 7d Summary for Pro+ and Elite
    if summary_7d and user_plan in ['pro_plus', 'elite']:
        msg += "\n📅 <b>Last 7 Days:</b>\n"
        msg += format_period_summary(summary_7d, "7d")
    
    # Top transaction
    if summary_24h.get('largest_transaction'):
        largest = summary_24h['largest_transaction']
        msg += (
            f"\n🏆 <b>Largest 24h Transaction:</b>\n"
            f"💰 <b>{largest.get('amount_ton', 0):,.0f} TON</b>\n"
            f"💵 ~${largest.get('usd_value', 0):,.0f}\n"
            f"📤 {format_address(largest.get('from_address', ''))}\n"
            f"📥 {format_address(largest.get('to_address', ''))}\n"
        )
    
    # Market impact for Elite
    if user_plan == 'elite':
        msg += get_market_impact_analysis(summary_24h)
    
    return msg

def format_period_summary(summary: Dict, period: str) -> str:
    """Format summary data for a specific period"""
    if not summary or summary.get('total_transactions', 0) == 0:
        return f"No major activity in {period}\n"
    
    total_tx = summary.get('total_transactions', 0)
    total_volume = summary.get('total_volume_ton', 0)
    total_usd = summary.get('total_usd_value', 0)
    breakdown = summary.get('whale_breakdown', {})
    
    msg = (
        f"🔢 <b>Transactions:</b> {total_tx}\n"
        f"💎 <b>Volume:</b> {total_volume:,.0f} TON\n"
        f"💵 <b>USD Value:</b> ${total_usd:,.0f}\n"
    )
    
    if breakdown:
        msg += f"📊 <b>Breakdown:</b> "
        breakdown_parts = []
        for category, count in breakdown.items():
            emoji = WHALE_EMOJIS.get(category, '⚪')
            breakdown_parts.append(f"{emoji}{count}")
        msg += " | ".join(breakdown_parts) + "\n"
    
    return msg

def create_whale_action_keyboard(has_premium: bool, user_plan: str) -> types.InlineKeyboardMarkup:
    """Create action keyboard for whale alerts"""
    if has_premium:
        return types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="📊 24h Summary", callback_data="whale_summary_24h"),
                types.InlineKeyboardButton(text="🔄 Refresh", callback_data="whale_refresh")
            ],
            [
                types.InlineKeyboardButton(text="⚙️ Settings", callback_data="whale_settings"),
                types.InlineKeyboardButton(text="📈 Analytics", callback_data="whale_analytics")
            ]
        ])
    else:
        return types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="💎 Upgrade to Premium", callback_data="upgrade_premium"),
                types.InlineKeyboardButton(text="🔄 Refresh", callback_data="whale_refresh")
            ]
        ])

def create_summary_action_keyboard(user_plan: str) -> types.InlineKeyboardMarkup:
    """Create action keyboard for whale summary"""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="🔄 Refresh Data", callback_data="whale_summary_refresh"),
            types.InlineKeyboardButton(text="🐋 Live Alerts", callback_data="whale_refresh")
        ]
    ])

def classify_whale_transaction(amount_ton: float) -> str:
    """Classify transaction by whale category"""
    if amount_ton >= WHALE_THRESHOLDS['mega_whale']:
        return 'mega_whale'
    elif amount_ton >= WHALE_THRESHOLDS['large_whale']:
        return 'large_whale'
    elif amount_ton >= WHALE_THRESHOLDS['medium_whale']:
        return 'medium_whale'
    elif amount_ton >= WHALE_THRESHOLDS['small_whale']:
        return 'small_whale'
    else:
        return 'regular'

def format_address(address: str) -> str:
    """Format TON address for display"""
    if not address or address == 'unknown':
        return 'Unknown'
    
    if len(address) > 12:
        return f"{address[:6]}...{address[-6:]}"
    return address

def format_timestamp(timestamp: int) -> str:
    """Format timestamp to readable string"""
    try:
        dt = datetime.fromtimestamp(timestamp)
        now = datetime.now()
        diff = now - dt
        
        if diff.total_seconds() < 3600:  # Less than 1 hour
            minutes = int(diff.total_seconds() // 60)
            return f"{minutes}m ago"
        elif diff.total_seconds() < 86400:  # Less than 1 day
            hours = int(diff.total_seconds() // 3600)
            return f"{hours}h ago"
        else:
            return dt.strftime("%m/%d %H:%M")
    except:
        return "Unknown"

def get_market_impact_analysis(summary: Dict) -> str:
    """Generate market impact analysis for Elite users"""
    volume = summary.get('total_volume_ton', 0)
    
    if volume < 10000:
        impact = "Minimal market impact expected"
        recommendation = "Hold current positions"
    elif volume < 100000:
        impact = "Low-moderate market pressure"
        recommendation = "Monitor for trend changes"
    elif volume < 500000:
        impact = "Moderate market impact likely"
        recommendation = "Consider position adjustments"
    else:
        impact = "High market impact - monitor closely"
        recommendation = "Review risk management"
    
    return (
        f"\n📈 <b>Market Impact Analysis (Elite):</b>\n"
        f"🎯 <b>Assessment:</b> {impact}\n"
        f"📊 <b>Recommendation:</b> {recommendation}\n"
    )

def register_whale_handlers(dp):
    """Register whale handlers with the dispatcher"""
    dp.include_router(router)
    logger.info("✅ Whale handlers registered")