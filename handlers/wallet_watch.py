# handlers/wallet_watch.py
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from services.tonapi import get_wallet_info, get_wallet_transactions
from utils.redis_conn import redis_client
import logging
from datetime import datetime
from typing import Dict, List

logger = logging.getLogger(__name__)
router = Router()

class WalletWatchStates(StatesGroup):
    WaitingForAddress = State()

@router.message(Command("wallet_watch"))
async def wallet_watch_start(message: types.Message, state: FSMContext):
    """Start wallet watching process"""
    await message.answer(
        "👛 <b>Wallet Watch System</b>\n\n"
        "📍 Please enter the TON wallet address to monitor:\n\n"
        "💡 <b>Features:</b>\n"
        "• Real-time transaction monitoring\n"
        "• Balance tracking\n"
        "• Whale categorization\n"
        "• Transaction history\n\n"
        "🔒 <i>Send the wallet address to continue...</i>",
        parse_mode="HTML"
    )
    await state.set_state(WalletWatchStates.WaitingForAddress)

@router.message(WalletWatchStates.WaitingForAddress)
async def wallet_watch_address(message: types.Message, state: FSMContext):
    """Process wallet address and add to watchlist"""
    address = message.text.strip()
    user_id = str(message.from_user.id)
    
    # Validate address format (basic validation)
    if len(address) < 48 or not address.replace('-', '').replace('_', '').isalnum():
        await message.answer(
            "❌ <b>Invalid Address Format</b>\n\n"
            "Please enter a valid TON wallet address.\n"
            "Example: <code>EQD...abc123</code>",
            parse_mode="HTML"
        )
        return
    
    try:
        # Add to Redis watchlist
        redis_client.sadd(f"wallets:{user_id}", address)
        
        await message.answer(
            f"✅ <b>Wallet Added to Watchlist</b>\n\n"
            f"📍 <code>{format_address(address)}</code>\n\n"
            f"🔄 Fetching wallet information...",
            parse_mode="HTML"
        )
        
        # Get wallet information
        wallet_info = await get_wallet_info(address)
        
        if wallet_info.get('error'):
            await message.answer(
                f"⚠️ <b>Wallet Added but Info Unavailable</b>\n\n"
                f"The wallet has been added to your watchlist, but we couldn't fetch current information.\n\n"
                f"📍 Address: <code>{format_address(address)}</code>\n"
                f"🔄 Try /wallet_info {address} later",
                parse_mode="HTML"
            )
            await state.clear()
            return
        
        # Get recent transactions
        transactions_data = await get_wallet_transactions(address, limit=5)
        transactions = transactions_data.get('transactions', [])
        
        # Format wallet info response
        balance_ton = wallet_info.get('balance_ton', 0)
        balance_usd = wallet_info.get('balance_usd', 0)
        whale_category = wallet_info.get('whale_category', 'regular')
        last_activity = wallet_info.get('last_activity_formatted', 'Unknown')
        
        # Get whale emoji
        whale_emoji = get_whale_emoji(whale_category)
        whale_name = whale_category.replace('_', ' ').title()
        
        response = f"👛 <b>WALLET ANALYSIS</b>\n\n"
        response += f"📍 <b>Address:</b> <code>{format_address(address)}</code>\n"
        response += f"💰 <b>Balance:</b> {balance_ton:,.2f} TON\n"
        response += f"💵 <b>USD Value:</b> ${balance_usd:,.2f}\n"
        response += f"{whale_emoji} <b>Category:</b> {whale_name}\n"
        response += f"⏰ <b>Last Active:</b> {last_activity}\n\n"
        
        if transactions:
            response += f"📋 <b>Recent Transactions ({len(transactions)}):</b>\n"
            for i, tx in enumerate(transactions, 1):
                amount_ton = tx.get('amount_ton', 0)
                tx_type = tx.get('type', 'unknown').replace('_', ' ').title()
                time_str = format_timestamp(tx.get('timestamp', 0))
                
                response += f"{i}. <b>{amount_ton:,.2f} TON</b> | {tx_type}\n"
                response += f"   🕐 {time_str}\n"
                
                if amount_ton > 1000:  # Mark large transactions
                    response += f"   🐋 Large Transaction\n"
                response += "\n"
        else:
            response += "📋 <b>Recent Transactions:</b> None found\n\n"
        
        # Add action buttons
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="🔄 Refresh Info", callback_data=f"refresh_wallet_{address}"),
                types.InlineKeyboardButton(text="📋 More Transactions", callback_data=f"more_tx_{address}")
            ],
            [
                types.InlineKeyboardButton(text="📊 Analytics", callback_data=f"wallet_analytics_{address}"),
                types.InlineKeyboardButton(text="🗑️ Remove from Watchlist", callback_data=f"remove_wallet_{address}")
            ]
        ])
        
        response += "💡 <b>Commands:</b>\n"
        response += "• /my_wallets - View all watched wallets\n"
        response += "• /transactions <address> - Get detailed transaction history\n"
        response += "• /wallet_alerts - Configure notifications"
        
        await message.answer(response, parse_mode="HTML", reply_markup=keyboard)
        
        # Log successful addition
        logger.info(f"Wallet {format_address(address)} added to watchlist for user {user_id}")
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Wallet watch error for user {user_id}: {error_msg}")
        
        await message.answer(
            f"⚠️ <b>Error Processing Wallet</b>\n\n"
            f"🔧 Could not process the wallet address.\n"
            f"Please verify the address and try again.\n\n"
            f"💡 <b>Tips:</b>\n"
            f"• Ensure the address is complete\n"
            f"• Check for typos or extra spaces\n"
            f"• Try again in a few moments\n\n"
            f"🛠️ Error: <code>{error_msg[:100]}...</code>",
            parse_mode="HTML"
        )
    
    await state.clear()

@router.message(Command("my_wallets"))
async def my_wallets_command(message: types.Message):
    """Show user's watched wallets"""
    user_id = str(message.from_user.id)
    
    try:
        # Get watched wallets from Redis
        watched_wallets = redis_client.smembers(f"wallets:{user_id}")
        
        if not watched_wallets:
            await message.reply(
                "📭 <b>No Wallets in Watchlist</b>\n\n"
                "Use /wallet_watch to add a wallet to monitor.\n\n"
                "💡 <b>Benefits of wallet watching:</b>\n"
                "• Track balance changes\n"
                "• Monitor transaction activity\n"
                "• Get whale alerts\n"
                "• Historical analysis",
                parse_mode="HTML"
            )
            return
        
        response = f"👛 <b>YOUR WATCHLIST ({len(watched_wallets)} wallets)</b>\n\n"
        
        for i, wallet_bytes in enumerate(watched_wallets, 1):
            wallet = wallet_bytes.decode('utf-8') if isinstance(wallet_bytes, bytes) else wallet_bytes
            
            # Get quick wallet info
            try:
                info = await get_wallet_info(wallet)
                balance = info.get('balance_ton', 0)
                whale_category = info.get('whale_category', 'regular')
                whale_emoji = get_whale_emoji(whale_category)
                
                response += f"{i}. {whale_emoji} <code>{format_address(wallet)}</code>\n"
                response += f"   💰 {balance:,.2f} TON\n"
                response += f"   🏷️ {whale_category.replace('_', ' ').title()}\n\n"
                
            except Exception as e:
                response += f"{i}. ⚪ <code>{format_address(wallet)}</code>\n"
                response += f"   ❌ Info unavailable\n\n"
        
        # Add management buttons
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="🔄 Refresh All", callback_data="refresh_all_wallets"),
                types.InlineKeyboardButton(text="➕ Add Wallet", callback_data="add_new_wallet")
            ],
            [
                types.InlineKeyboardButton(text="🔔 Alert Settings", callback_data="wallet_alert_settings"),
                types.InlineKeyboardButton(text="🗑️ Manage Watchlist", callback_data="manage_watchlist")
            ]
        ])
        
        response += "💡 Click a wallet to see detailed info"
        
        await message.reply(response, parse_mode="HTML", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error fetching watchlist for user {user_id}: {e}")
        await message.reply("❌ Error loading watchlist. Please try again.")

@router.message(Command("transactions"))
async def transactions_command(message: types.Message):
    """Get detailed transaction history for a wallet"""
    try:
        args = message.text.split()[1:]
        if not args:
            await message.reply(
                "❌ <b>Missing Wallet Address</b>\n\n"
                "Usage: <code>/transactions &lt;wallet_address&gt;</code>\n\n"
                "💡 Or use /my_wallets to see your watched addresses",
                parse_mode="HTML"
            )
            return
        
        address = args[0]
        limit = int(args[1]) if len(args) > 1 and args[1].isdigit() else 10
        limit = min(limit, 20)  # Max 20 transactions
        
        await message.reply(f"📋 Loading {limit} transactions for <code>{format_address(address)}</code>...", parse_mode="HTML")
        
        # Get transaction data
        tx_data = await get_wallet_transactions(address, limit=limit)
        transactions = tx_data.get('transactions', [])
        
        if not transactions:
            await message.reply(
                f"📋 <b>No Transactions Found</b>\n\n"
                f"📍 Wallet: <code>{format_address(address)}</code>\n"
                f"🔍 No transaction history available\n\n"
                f"💡 This could mean:\n"
                f"• New/unused wallet\n"
                f"• Private transaction history\n"
                f"• Temporary API issue",
                parse_mode="HTML"
            )
            return
        
        response = f"📋 <b>TRANSACTION HISTORY</b>\n\n"
        response += f"📍 <b>Wallet:</b> <code>{format_address(address)}</code>\n"
        response += f"📊 <b>Showing:</b> {len(transactions)} of {limit} requested\n\n"
        
        total_in = 0
        total_out = 0
        
        for i, tx in enumerate(transactions, 1):
            amount_ton = tx.get('amount_ton', 0)
            tx_type = tx.get('type', 'unknown')
            time_str = format_timestamp(tx.get('timestamp', 0))
            hash_short = tx.get('hash', 'unknown')[:8] + '...'
            
            # Determine if incoming or outgoing
            is_incoming = tx.get('direction') == 'in' or tx_type in ['receive', 'incoming']
            direction_emoji = "📥" if is_incoming else "📤"
            
            if is_incoming:
                total_in += amount_ton
            else:
                total_out += amount_ton
            
            # Get whale category for large transactions
            whale_indicator = ""
            if amount_ton > 1000:
                whale_category = tx.get('whale_category', 'large')
                whale_emoji = get_whale_emoji(whale_category)
                whale_indicator = f" {whale_emoji}"
            
            response += f"{i}. {direction_emoji} <b>{amount_ton:,.2f} TON</b>{whale_indicator}\n"
            response += f"   🕐 {time_str} | 🔗 {hash_short}\n"
            response += f"   🏷️ {tx_type.replace('_', ' ').title()}\n\n"
        
        # Add summary
        response += f"📊 <b>Summary:</b>\n"
        response += f"📥 Total In: <b>{total_in:,.2f} TON</b>\n"
        response += f"📤 Total Out: <b>{total_out:,.2f} TON</b>\n"
        response += f"📈 Net Flow: <b>{total_in - total_out:,.2f} TON</b>\n\n"
        
        # Add action buttons
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="🔄 Refresh", callback_data=f"refresh_tx_{address}"),
                types.InlineKeyboardButton(text="📊 More History", callback_data=f"more_tx_{address}")
            ],
            [
                types.InlineKeyboardButton(text="👛 Wallet Info", callback_data=f"wallet_info_{address}"),
                types.InlineKeyboardButton(text="➕ Add to Watchlist", callback_data=f"add_watch_{address}")
            ]
        ])
        
        response += "💡 Use /wallet_watch to add this wallet to your monitoring list"
        
        await message.reply(response, parse_mode="HTML", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error in transactions command: {e}")
        await message.reply(
            f"⚠️ <b>Transaction Fetch Error</b>\n\n"
            f"Could not retrieve transaction history.\n\n"
            f"💡 <b>Please try:</b>\n"
            f"• Verify the wallet address\n"
            f"• Check your internet connection\n"
            f"• Try again in a few moments\n\n"
            f"🛠️ Error: <code>{str(e)[:100]}...</code>",
            parse_mode="HTML"
        )

@router.message(Command("watch"))
async def quick_watch_command(message: types.Message):
    """Quick wallet watch without FSM"""
    try:
        args = message.text.split()[1:]
        if not args:
            await message.reply(
                "❌ <b>Usage:</b> <code>/watch &lt;wallet_address&gt;</code>\n\n"
                "💡 Or use /wallet_watch for guided setup",
                parse_mode="HTML"
            )
            return
        
        address = args[0].strip()
        user_id = str(message.from_user.id)
        
        # Add to watchlist
        redis_client.sadd(f"wallets:{user_id}", address)
        
        await message.reply(f"👀 <b>Quick Watch Activated</b>\n\n📍 <code>{format_address(address)}</code>", parse_mode="HTML")
        
        # Get and display wallet info
        info = await get_wallet_info(address)
        
        if info.get('error'):
            await message.reply("⚠️ Wallet added to watchlist, but info currently unavailable.")
            return
        
        balance_ton = info.get('balance_ton', 0)
        balance_usd = info.get('balance_usd', 0)
        whale_category = info.get('whale_category', 'regular')
        whale_emoji = get_whale_emoji(whale_category)
        
        response = f"👛 <b>WALLET OVERVIEW</b>\n\n"
        response += f"📍 <code>{format_address(address)}</code>\n"
        response += f"💰 <b>{balance_ton:,.2f} TON</b> (${balance_usd:,.2f})\n"
        response += f"{whale_emoji} <b>{whale_category.replace('_', ' ').title()}</b>\n\n"
        response += "✅ Added to your watchlist!"
        
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="📋 Transactions", callback_data=f"show_tx_{address}"),
                types.InlineKeyboardButton(text="📊 Analytics", callback_data=f"wallet_analytics_{address}")
            ]
        ])
        
        await message.reply(response, parse_mode="HTML", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error in quick watch command: {e}")
        await message.reply(f"❌ Error watching wallet: {e}")

# Callback handlers
@router.callback_query(lambda c: c.data.startswith("refresh_wallet_"))
async def refresh_wallet_callback(callback_query: types.CallbackQuery):
    """Refresh wallet information"""
    address = callback_query.data.replace("refresh_wallet_", "")
    await callback_query.answer("🔄 Refreshing wallet data...")
    
    try:
        info = await get_wallet_info(address)
        
        if info.get('error'):
            await callback_query.message.edit_text(
                f"⚠️ <b>Refresh Failed</b>\n\n"
                f"Could not fetch updated information for:\n"
                f"<code>{format_address(address)}</code>",
                parse_mode="HTML"
            )
            return
        
        # Update with fresh data
        balance_ton = info.get('balance_ton', 0)
        balance_usd = info.get('balance_usd', 0)
        whale_category = info.get('whale_category', 'regular')
        whale_emoji = get_whale_emoji(whale_category)
        last_activity = info.get('last_activity_formatted', 'Unknown')
        
        updated_msg = f"👛 <b>WALLET INFO (UPDATED)</b>\n\n"
        updated_msg += f"📍 <code>{format_address(address)}</code>\n"
        updated_msg += f"💰 <b>{balance_ton:,.2f} TON</b> (${balance_usd:,.2f})\n"
        updated_msg += f"{whale_emoji} <b>{whale_category.replace('_', ' ').title()}</b>\n"
        updated_msg += f"⏰ <b>Last Active:</b> {last_activity}\n"
        updated_msg += f"🔄 <b>Updated:</b> {datetime.now().strftime('%H:%M:%S')}"
        
        # Keep original keyboard
        keyboard = callback_query.message.reply_markup
        
        await callback_query.message.edit_text(updated_msg, parse_mode="HTML", reply_markup=keyboard)
        
    except Exception as e:
        await callback_query.answer(f"❌ Refresh failed: {e}", show_alert=True)

@router.callback_query(lambda c: c.data.startswith("remove_wallet_"))
async def remove_wallet_callback(callback_query: types.CallbackQuery):
    """Remove wallet from watchlist"""
    address = callback_query.data.replace("remove_wallet_", "")
    user_id = str(callback_query.from_user.id)
    
    try:
        # Remove from Redis
        removed = redis_client.srem(f"wallets:{user_id}", address)
        
        if removed:
            await callback_query.answer("✅ Wallet removed from watchlist", show_alert=True)
            
            updated_msg = f"🗑️ <b>Wallet Removed</b>\n\n"
            updated_msg += f"📍 <code>{format_address(address)}</code>\n"
            updated_msg += f"✅ Successfully removed from your watchlist\n\n"
            updated_msg += "💡 Use /wallet_watch to add it back anytime"
            
            await callback_query.message.edit_text(updated_msg, parse_mode="HTML")
        else:
            await callback_query.answer("❌ Wallet not found in watchlist", show_alert=True)
            
    except Exception as e:
        await callback_query.answer(f"❌ Error removing wallet: {e}", show_alert=True)

# Helper functions
def get_whale_emoji(category: str) -> str:
    """Get emoji for whale category"""
    emojis = {
        'small_whale': '🟡',
        'medium_whale': '🟠',
        'large_whale': '🔴',
        'mega_whale': '🚨',
        'regular': '⚪'
    }
    return emojis.get(category, '⚪')

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
        
        if diff.total_seconds() < 60:  # Less than 1 minute
            return "Just now"
        elif diff.total_seconds() < 3600:  # Less than 1 hour
            minutes = int(diff.total_seconds() // 60)
            return f"{minutes}m ago"
        elif diff.total_seconds() < 86400:  # Less than 1 day
            hours = int(diff.total_seconds() // 3600)
            return f"{hours}h ago"
        elif diff.total_seconds() < 604800:  # Less than 1 week
            days = int(diff.total_seconds() // 86400)
            return f"{days}d ago"
        else:
            return dt.strftime("%m/%d/%y")
    except:
        return "Unknown"

def register_wallet_handlers(dp):
    """Register wallet monitoring handlers"""
    dp.include_router(router)
    logger.info("✅ Wallet watch handlers registered")