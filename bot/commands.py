import asyncio
import time
from datetime import datetime
import logging
from aiogram import Router, types, Dispatcher
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, 
    InlineKeyboardButton, WebAppInfo
)

# Import existing services
from services.analysis import is_memecoin_only
from services.tonviewer_api import get_token_info_from_tonviewer
from utils.realtime_data import get_trending_tokens
from services.engine_client import engine_client

# Import database and utilities
# DatabaseManager removed - functionality moved to EngineClient

try:
    from utils.openai_client import OpenAIClient
except ImportError:
    OpenAIClient = None

try:
    from utils.ton_wallet import TonWallet
except ImportError:
    TonWallet = None

# Initialize logging
logger = logging.getLogger(__name__)

# Initialize rate limiter with proper error handling
try:
    from utils.redis_conn import redis_client
    from utils.rate_limiter import RateLimiter
    rate_limiter = RateLimiter(redis_client) if RateLimiter and redis_client else None
except ImportError:
    rate_limiter = None
    logger.warning("Rate limiter not available - imports missing")
except Exception as e:
    logger.error(f"Failed to initialize rate limiter: {e}")
    rate_limiter = None

# Import monitoring system (fallback if not available)
try:
    from core.monitoring import (
        monitor_request,
        get_logger,
        get_prometheus_metrics,
        monitor_function
    )
    monitoring_available = True
except ImportError:
    # Fallback decorators if monitoring not available
    def monitor_request(operation, user_id, tier="free"):
        class DummyContext:
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
        return DummyContext()
    
    def monitor_function(operation):
        def decorator(func):
            return func
        return decorator
    
    monitoring_available = False
    logger.warning("Monitoring system not available")

# Initialize monitoring components
if monitoring_available:
    monitoring_logger = get_logger()
    prometheus = get_prometheus_metrics()
else:
    monitoring_logger = None
    prometheus = None

# Initialize clients with safe fallbacks
openai_client = OpenAIClient() if OpenAIClient else None
ton_wallet = TonWallet() if TonWallet else None

# Create router for commands
router = Router()

# Global subscription manager removed - using EngineClient directly

# ==================== HELPER FUNCTIONS ====================

def get_memecoin_emoji(name):
    """Get appropriate emoji for memecoin based on name"""
    name_lower = name.lower()
    
    emoji_map = {
        ('cat', 'kitten', 'cate'): "🐱",
        ('dog', 'puppy', 'doge', 'inu'): "🐕", 
        ('frog', 'pepe'): "🐸",
        ('hamster',): "🐹",
        ('moon', 'rocket'): "🚀",
        ('diamond',): "💎",
        ('pig',): "🐷",
        ('bear',): "🐻",
        ('bull',): "🐂"
    }
    
    for keywords, emoji in emoji_map.items():
        if any(word in name_lower for word in keywords):
            return emoji
    
    return "🎯"

def categorize_memecoins(memecoins):
    """Categorize memecoins by type"""
    categories = {
        'animal': [],
        'moon': [],
        'meme': [],
        'other': [],
        'top_performers': []
    }
    
    try:
        for token in memecoins:
            # Handle both dict-like objects and TokenData objects
            name = getattr(token, 'name', '') if hasattr(token, 'name') else token.get('name', '')
            symbol = getattr(token, 'symbol', '') if hasattr(token, 'symbol') else token.get('symbol', '')
            
            name_lower = str(name).lower()
            symbol_lower = str(symbol).lower()
            
            animal_keywords = ['dog', 'cat', 'inu', 'shib', 'hamster', 'pig', 'bear', 'bull', 'lion', 'tiger', 'wolf', 'fox', 'rabbit', 'puppy', 'kitten']
            moon_keywords = ['moon', 'rocket', 'lambo', 'diamond']
            meme_keywords = ['meme', 'pepe', 'wojak', 'chad', 'based']
            
            if any(word in name_lower or word in symbol_lower for word in animal_keywords):
                categories['animal'].append(token)
            elif any(word in name_lower or word in symbol_lower for word in moon_keywords):
                categories['moon'].append(token)
            elif any(word in name_lower or word in symbol_lower for word in meme_keywords):
                categories['meme'].append(token)
            else:
                categories['other'].append(token)
        
        # Top performers by volume
        memecoins_with_volume = []
        for token in memecoins:
            volume_24h = getattr(token, 'volume_24h', 0) if hasattr(token, 'volume_24h') else token.get('volume_24h', 0)
            if volume_24h and str(volume_24h).replace('.', '').replace('$', '').replace(',', '').replace('-', '').replace('e', '').isdigit():
                memecoins_with_volume.append(token)
        
        if memecoins_with_volume:
            def get_volume(token):
                volume = getattr(token, 'volume_24h', 0) if hasattr(token, 'volume_24h') else token.get('volume_24h', 0)
                try:
                    return float(str(volume).replace('$', '').replace(',', '') or 0)
                except (ValueError, TypeError):
                    return 0
            
            categories['top_performers'] = sorted(memecoins_with_volume, key=get_volume, reverse=True)
            
    except Exception as e:
        logger.error(f"Categorization error: {e}")
    
    return categories

async def check_user_credits(user_id, credits_needed=1):
    """Check and consume user credits"""
    if not redis_client:
        return True
        
    try:
        # Get limits and usage from Redis (managed by pay.py/Engine)
        limit_key = f"plan_queries:{user_id}"
        usage_key = f"usage_today:{user_id}"
        
        limit = redis_client.get(limit_key)
        limit = int(limit) if limit else 10  # Default 10 if no plan
        
        if limit == -1: # Unlimited
            return True
            
        usage = redis_client.get(usage_key)
        usage = int(usage) if usage else 0
        
        if usage + credits_needed > limit:
            return False
            
        redis_client.incrby(usage_key, credits_needed)
        return True
        
    except Exception as e:
        logger.error(f"Credit check error: {e}")
        return True  # Default to allow on error

async def check_rate_limit(user_id, tier="free"):
    """Check user rate limits"""
    if not rate_limiter:
        return True
    
    try:
        is_limited, info = await rate_limiter.check_rate_limit(user_id, tier)
        return not is_limited
    except Exception as e:
        logger.error(f"Rate limit check error: {e}")
        return True  # Default to allow on error

def log_user_action(user_id, action, success=True, metadata=None):
    """Safe logging wrapper using EngineClient"""
    # Fire and forget async logging
    asyncio.create_task(
        engine_client.log_activity(
            user_id, 
            action, 
            {"success": success, **(metadata or {})}
        )
    )

def format_token_data(token):
    """Format token data for display, handling both TokenData objects and dicts"""
    try:
        name = getattr(token, 'name', 'Unknown') if hasattr(token, 'name') else token.get('name', 'Unknown')
        symbol = getattr(token, 'symbol', 'N/A') if hasattr(token, 'symbol') else token.get('symbol', 'N/A')
        price_usd = getattr(token, 'price_usd', 0) if hasattr(token, 'price_usd') else token.get('price_usd', token.get('price', 0))
        volume_24h = getattr(token, 'volume_24h', 0) if hasattr(token, 'volume_24h') else token.get('volume_24h', 0)
        price_change_24h = getattr(token, 'price_change_24h', 0) if hasattr(token, 'price_change_24h') else token.get('price_change_24h', 0)
        dex = getattr(token, 'dex', 'STON.fi') if hasattr(token, 'dex') else token.get('dex', 'STON.fi')
        
        return {
            'name': str(name),
            'symbol': str(symbol),
            'price': float(price_usd) if price_usd else 0.0,
            'volume_24h': float(volume_24h) if volume_24h else 0.0,
            'price_change_24h': float(price_change_24h) if price_change_24h else 0.0,
            'dex': str(dex)
        }
    except Exception as e:
        logger.error(f"Token formatting error: {e}")
        return {
            'name': 'Unknown',
            'symbol': 'N/A',
            'price': 0.0,
            'volume_24h': 0.0,
            'price_change_24h': 0.0,
            'dex': 'DEX'
        }

# ==================== ENHANCED CORE COMMANDS ====================

@router.message(Command("start"))
async def start_command(message: types.Message):
    """Enhanced start command with monitoring and subscription integration"""
    user = message.from_user
    user_id = user.id
    username = user.username or "unknown"
    
    # Sync user with Engine
    try:
        await engine_client.create_or_update_user(
            telegram_id=user_id,
            username=username,
            first_name=user.first_name,
            last_name=user.last_name
        )
    except Exception as e:
        logger.error(f"Failed to sync user {user_id}: {e}")
    
    # Determine user tier
    user_tier = "free"
    
    # Use remote logging instead of local context manager if possible, or keep simple
    try:
        # Get subscription status
        subscription_status = ""
        try:
            status_data = await engine_client.get_user_status(str(user_id))
            user_tier = status_data.get("plan", "Free").lower()
            if user_tier != "free":
                subscription_status = f"\n💎 Plan: {user_tier.title()}"
        except Exception as e:
            logger.warning(f"Subscription check failed: {e}")
        
        start_text = (
            f"👋 Hello {user.first_name}!{subscription_status}\n\n"
            "I'm TonGPT, your smart AI analyst for TON memecoins. "
            "Ask me about trending memecoins, market analysis and more.\n\n"
            "🔥 Pure TON memecoin focus - no major cryptos!\n\n"
            "💡 Quick start:\n"
            "• /scan - See trending memecoins\n"  
            "• /ask [question] - AI analysis\n"
            "• /app - Web interface\n"
            "• /help - All commands\n\n"
            "🚀 Use /subscription to check your plan!"
        )
        
        # Create keyboard
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🔍 Scan Memecoins")],
                [KeyboardButton(text="💬 Chat with AI")],
                [KeyboardButton(text="💎 Premium"), KeyboardButton(text="📊 My Stats")]
            ],
            resize_keyboard=True
        )
        
        await message.answer(start_text, parse_mode="HTML", reply_markup=keyboard)
        
        # Log via Engine
        await engine_client.log_activity(user_id, "start_command", {"tier": user_tier, "username": username})
        
    except Exception as e:
        await engine_client.log_activity(user_id, "start_command", {"error": str(e), "success": False})
        await message.answer("❌ Sorry, something went wrong. Please try again later.")
        logger.error(f"Start command error: {e}")

@router.message(Command("help"))
@monitor_function("bot_command_help")
async def help_command(message: types.Message):
    """Comprehensive help command with monitoring"""
    user_id = message.from_user.id
    
    help_text = (
        "🤖 <b>TonGPT Bot Commands</b>\n\n"
        
        "🔥 <b>Pure Memecoin Analysis:</b>\n"
        "• /scan - Discover trending TON memecoins ONLY\n"
        "• /trending - Pure memecoin market trends\n"
        "• /info [contract] - Token details by address\n\n"
        
        "💬 <b>AI Assistance:</b>\n"
        "• /ask [question] - AI analysis (costs 1 credit)\n"
        "• Just message me directly for AI chat\n\n"
        
        "🐦 <b>Social Intelligence:</b>\n"
        "• /X - Twitter/X monitoring dashboard\n"
        "• /influencer - Crypto influencer tracking\n\n"
        
        "💎 <b>Subscription:</b>\n"
        "• /subscription - View plan details\n"
        "• /upgrade - Upgrade your plan\n"
        "• /sub - Quick status check\n"
        "• /stats - Usage statistics\n\n"
        
        "🚀 <b>Tools & Community:</b>\n"
        "• /app - Launch web interface\n"
        "• /refer - Get referral rewards\n"
        "• /join - Community links\n"
        "• /support - Contact support\n\n"
        
        "🎯 <b>Focus:</b> Pure TON memecoins only - no major cryptos!\n"
        "💡 <b>Tip:</b> Free plan includes 100 credits/month"
    )

    await message.reply(help_text, parse_mode="HTML")
    log_user_action(user_id, "help_command", True)

@router.message(Command("scan"))
async def scan_command(message: types.Message):
    """Enhanced scan command with credit consumption and comprehensive monitoring"""
    user_id = message.from_user.id
    
    # Determine user tier
    user_tier = "free"
    try:
        status = await engine_client.get_user_status(str(user_id))
        user_tier = status.get("plan", "Free").lower()
    except Exception:
        pass
    
    async with monitor_request("bot_command_scan", user_id, user_tier):
        try:
            # Check and consume credits
            can_use = await check_user_credits(user_id, 1)
            if not can_use:
                await message.reply(
                    "❌ <b>Insufficient Credits</b>\n\n"
                    "You've run out of credits for scanning.\n"
                    "Use /subscription to check your plan or /upgrade for more credits!",
                    parse_mode="HTML"
                )
                return
            
            # Check rate limits
            if not await check_rate_limit(user_id, user_tier):
                await message.reply(
                    "⏰ You've reached your request limit. "
                    "Upgrade to premium for higher limits!"
                )
                return
            
            await message.reply("🔍 Scanning TON blockchain for trending memecoins...")
            await message.bot.send_chat_action(message.chat.id, "typing")
            
            start_time = time.time()
            
            # Get live token data
            try:
                tokens = get_trending_tokens(15)  # Get 15 trending tokens
                response_time = (time.time() - start_time) * 1000
                
                # Record API metrics if available
                if prometheus:
                    prometheus.record_request("memecoin_api", "success", response_time / 1000, user_tier)
                
            except Exception as fetch_error:
                response_time = (time.time() - start_time) * 1000
                
                if prometheus:
                    prometheus.record_request("memecoin_api", "error", response_time / 1000, user_tier)
                
                logger.error(f"Token fetching error: {fetch_error}")
                await message.reply("❌ Unable to fetch live data. API service may be down.")
                return
            
            if not tokens or len(tokens) == 0:
                await message.reply("❌ No token data available right now. Please try again.")
                return
            
            # Apply strict memecoin filtering
            try:
                memecoins = [token for token in tokens if is_memecoin_only(token)]
            except Exception as filter_error:
                logger.error(f"Filtering error: {filter_error}")
                memecoins = tokens[:10]  # Fallback to showing first 10 tokens
            
            if not memecoins:
                await message.reply(
                    "🔍 No pure memecoins found at the moment.\n\n"
                    "This could mean:\n"
                    "• Major tokens dominating the market\n"
                    "• Low memecoin activity\n"
                    "• API limitations\n\n"
                    "Try again in a few minutes!"
                )
                return
            
            # Format response for pure memecoins only
            msg = "🔥 **PURE TON MEMECOINS ONLY** 🚀\n\n"
            
            # Sort by volume with error handling
            try:
                def get_volume_for_sort(token):
                    try:
                        volume = getattr(token, 'volume_24h', 0) if hasattr(token, 'volume_24h') else token.get('volume_24h', 0)
                        return float(str(volume).replace('$', '').replace(',', '') or 0)
                    except:
                        return 0
                
                memecoins_sorted = sorted(memecoins, key=get_volume_for_sort, reverse=True)
            except Exception:
                memecoins_sorted = memecoins
            
            for i, token in enumerate(memecoins_sorted[:10], 1):
                try:
                    token_data = format_token_data(token)
                    
                    # Add emoji based on name
                    emoji = get_memecoin_emoji(token_data['name'])
                    
                    msg += f"{emoji} {i}. **{token_data['name']}** (${token_data['symbol']})\n"
                    msg += f"   💰 ${token_data['price']:.6f}"
                    
                    if token_data['volume_24h'] > 0:
                        msg += f" | 📊 Vol: ${token_data['volume_24h']:,.0f}"
                    
                    if token_data['price_change_24h'] != 0:
                        change_emoji = "📈" if token_data['price_change_24h'] > 0 else "📉"
                        msg += f" | {change_emoji} {token_data['price_change_24h']:.1f}%"
                    
                    msg += f"\n   🔗 {token_data['dex']}\n\n"
                    
                except Exception as format_error:
                    logger.error(f"Token formatting error: {format_error}")
                    continue
            
            msg += f"📊 **Pure Memecoins Found:** {len(memecoins)}\n"
            msg += "⚡ **Data:** Live from DEXs (Major tokens filtered)\n\n"
            msg += "💡 Use `/ask` for detailed analysis!"
            
            await message.reply(msg, parse_mode="Markdown")
            
            log_user_action(user_id, "scan_command", True, {
                "tier": user_tier,
                "tokens_found": len(memecoins),
                "response_time_ms": response_time
            })
                
        except Exception as e:
            log_user_action(user_id, "scan_command", False, {"tier": user_tier, "error": str(e)})
            logger.error(f"Error in scan command: {e}")
            await message.reply("❌ Scan service temporarily unavailable.")

@router.message(Command("ask"))
async def ask_command(message: types.Message):
    """Enhanced ask command with credit consumption and rate limiting"""
    user_id = message.from_user.id
    
    # Determine user tier
    user_tier = "free"
    try:
        status = await engine_client.get_user_status(str(user_id))
        user_tier = status.get("plan", "Free").lower()
    except Exception:
        pass
    
    async with monitor_request("bot_command_ask", user_id, user_tier):
        try:
            # Check and consume credits
            can_use = await check_user_credits(user_id, 1)
            if not can_use:
                await message.reply(
                    "❌ <b>Insufficient Credits</b>\n\n"
                    "You've run out of credits for AI queries.\n"
                    "Use /subscription to check your plan or /upgrade for more credits!",
                    parse_mode="HTML"
                )
                return
            
            # Check rate limits
            if not await check_rate_limit(user_id, user_tier):
                await message.reply(
                    "⏰ You've reached your message limit. "
                    "Upgrade to premium for unlimited messages!"
                )
                return
            
            # Try to import and use GPT handler
            try:
                from handlers.gpt_reply import handle_gpt_query
                await handle_gpt_query(message)
                log_user_action(user_id, "ask_command", True, {"tier": user_tier})
                
            except ImportError:
                logger.warning("GPT handler not available")
                await message.reply(
                    "🤖 AI features are currently being initialized.\n"
                    "Please try again in a moment."
                )
                
        except Exception as e:
            log_user_action(user_id, "ask_command", False, {"tier": user_tier, "error": str(e)})
            logger.error(f"Ask command error: {e}")
            await message.reply("❌ AI service temporarily unavailable.")

@router.message(Command("info"))
@monitor_function("bot_command_info")
async def info_command(message: types.Message):
    """Enhanced info command with monitoring and better error handling"""
    user_id = message.from_user.id
    
    try:
        if not message.text:
            await message.reply("❌ Usage: /info <contract_address>")
            return
        
        command_text = message.text.replace("/info", "", 1).strip()
        args = command_text.split() if command_text else []
        
        if not args:
            await message.reply("❌ Usage: /info <contract_address>")
            return
            
        contract = args[0]
        
        start_time = time.time()
        
        try:
            data = get_token_info_from_tonviewer(contract)
            response_time = (time.time() - start_time) * 1000
            
            if prometheus:
                prometheus.record_request("tonviewer_api", "success", response_time / 1000)
            
            if not data:
                await message.reply("❌ Token not found or invalid contract address.")
                return
                
            name = data.get("name", "Unknown")
            symbol = data.get("symbol", "")
            price = data.get("price", "N/A")
            holders = data.get("holders", "N/A")
            
            await message.reply(
                f"📊 <b>{name} ({symbol})</b>\n"
                f"💰 Price: {price}\n"
                f"👥 Holders: {holders}\n"
                f"🔗 Contract: <code>{contract}</code>",
                parse_mode="HTML"
            )
            
            log_user_action(user_id, "info_command", True, {
                "contract": contract,
                "response_time_ms": response_time
            })
            
        except Exception as api_error:
            response_time = (time.time() - start_time) * 1000
            
            if prometheus:
                prometheus.record_request("tonviewer_api", "error", response_time / 1000)
            
            logger.error(f"Token info API error: {api_error}")
            await message.reply("❌ Unable to fetch token information.")
            
    except Exception as e:
        log_user_action(user_id, "info_command", False, {"error": str(e)})
        logger.error(f"Info command error: {e}")
        await message.reply("❌ An error occurred.")

@router.message(Command("trending"))
@monitor_function("bot_command_trending")
async def trending_command(message: types.Message):
    """Enhanced trending command with monitoring and categorization"""
    user_id = message.from_user.id
    
    try:
        await message.reply("📈 Analyzing pure TON memecoin trends...")
        await message.bot.send_chat_action(message.chat.id, "typing")
        
        # Get token data
        try:
            tokens = get_trending_tokens(15)  # Get 15 trending tokens
        except Exception as fetch_error:
            logger.error(f"Trending fetch error: {fetch_error}")
            await message.reply("❌ Unable to fetch trend data.")
            return
        
        if not tokens:
            await message.reply("❌ No trend data available.")
            return
        
        # Filter for pure memecoins
        try:
            memecoins = [token for token in tokens if is_memecoin_only(token)]
        except Exception:
            memecoins = tokens[:10]  # Fallback to first 10 tokens
        
        if not memecoins:
            await message.reply("📈 No pure memecoin trends available right now.")
            return
        
        # Build trend analysis
        msg = "📈 **PURE TON MEMECOIN TRENDS** 🔥\n\n"
        
        # Categorize memecoins
        categories = categorize_memecoins(memecoins)
        
        msg += f"📊 **Market Overview:**\n"
        msg += f"• Total pure memecoins: {len(memecoins)}\n"
        msg += f"• Animal coins: {len(categories['animal'])}\n"
        msg += f"• Moon/rocket themed: {len(categories['moon'])}\n"
        msg += f"• Classic memes: {len(categories['meme'])}\n\n"
        
        # Top performers
        if categories['top_performers']:
            msg += "🚀 **TOP PERFORMERS:**\n"
            for i, token in enumerate(categories['top_performers'][:5], 1):
                token_data = format_token_data(token)
                emoji = get_memecoin_emoji(token_data['name'])
                msg += f"{emoji} {i}. **{token_data['name']}** | ${token_data['price']:.6f}\n"
        
        msg += "\n💡 Use `/scan` for live prices!"
        
        await message.reply(msg, parse_mode="Markdown")
        
        log_user_action(user_id, "trending_command", True, {"memecoins_analyzed": len(memecoins)})
        
    except Exception as e:
        log_user_action(user_id, "trending_command", False, {"error": str(e)})
        logger.error(f"Error in trending command: {e}")
        await message.reply("❌ Unable to analyze trends.")

# ==================== SUBSCRIPTION COMMANDS ====================

@router.message(Command("subscription", "sub"))
async def subscription_status_command(message: types.Message):
    """Display detailed subscription status with monitoring"""
    user_id = message.from_user.id
    
    async with monitor_request("bot_command_subscription", user_id):
        try:
            # Get status from C# Engine
            status_data = await engine_client.get_user_status(str(user_id))
            tier = status_data.get("plan", "Free").lower()
            
            # Determine credits/limits from local config/Redis backup
            limit_key = f"plan_queries:{user_id}"
            usage_key = f"usage_today:{user_id}"
            
            if redis_client:
                limit = redis_client.get(limit_key)
                limit = int(limit) if limit and int(limit) != -1 else (10000 if tier != 'free' else 10)
                if limit == -1: limit = "Unlimited"
                
                usage = redis_client.get(usage_key)
                usage = int(usage) if usage else 0
                credits_remaining = "Unlimited" if limit == "Unlimited" else (limit - usage)
            else:
                credits_remaining = "Unknown"

            status_text = (
                f"💎 <b>Your Subscription Details</b>\n\n"
                f"📋 Current Plan: <b>{tier.title()}</b>\n"
                f"⚡ Credits Remaining: <b>{credits_remaining}</b>\n"
            )
            
            expiry = status_data.get("expiry")
            if expiry:
                try:
                    dt = datetime.fromisoformat(expiry.replace('Z', '+00:00'))
                    status_text += f"📅 Expires: <b>{dt.strftime('%Y-%m-%d %H:%M')}</b>\n"
                except:
                    status_text += f"📅 Expires: <b>{expiry}</b>\n"
            else:
                status_text += f"📅 Plan: <b>Permanent (Free Tier)</b>\n"
            
            # status_text += f"📊 Member Since: <b>{subscription.created_at.strftime('%Y-%m-%d')}</b>\n\n"
            
            # Show plan benefits
            if tier == "free":
                status_text += (
                    "🆓 <b>Free Plan Features:</b>\n"
                    "• 100 credits/month\n"
                    "• 10 requests/hour\n"
                    "• Basic memecoin analysis\n\n"
                    "🚀 <b>Want More?</b>\n"
                    "Use /upgrade for premium features!"
                )
            elif tier == "basic":
                status_text += (
                    "🥉 <b>Basic Plan Features:</b>\n"
                    "• 1,000 credits/month\n"
                    "• 100 requests/hour\n"
                    "• Advanced AI analysis\n"
                    "• Priority support\n\n"
                    "🏆 Upgrade to Premium for even more!"
                )
            else:  # premium
                status_text += (
                    "🏆 <b>Premium Plan Features:</b>\n"
                    "• 10,000 credits/month\n"
                    "• 1,000 requests/hour\n"
                    "• Real-time whale alerts\n"
                    "• X monitoring alerts\n"
                    "• VIP support\n"
                    "• All features unlocked!"
                )
            
            # Add upgrade button for non-premium users
            if tier != "premium":
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚀 Upgrade Now", callback_data="start_upgrade")],
                    [InlineKeyboardButton(text="💬 Support", url="https://t.me/TonGPT_Support")]
                ])
                await message.reply(status_text, parse_mode="HTML", reply_markup=keyboard)
            else:
                await message.reply(status_text, parse_mode="HTML")
            
            log_user_action(user_id, "view_subscription", True, {
                "tier": tier,
                "credits_remaining": credits_remaining
            })
            
        except Exception as e:
            log_user_action(user_id, "view_subscription", False, {"error": str(e)})
            logger.error(f"Subscription status error: {e}")
            await message.reply("❌ Unable to fetch subscription status.")

# ==================== SOCIAL & UTILITY COMMANDS ====================

@router.message(Command("app"))
@monitor_function("bot_command_app")
async def open_app_command(message: types.Message):
    """Launch Mini App with monitoring"""
    user_id = message.from_user.id
    
    try:
        webapp_url = "https://tongpt.loca.lt"   
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🚀 Open TonGPT App", web_app=WebAppInfo(url=webapp_url))]
            ],
            resize_keyboard=True
        )
        await message.answer("Tap below to launch TonGPT Web App:", reply_markup=kb)
        log_user_action(user_id, "open_app", True)
        
    except Exception as e:
        log_user_action(user_id, "open_app", False, {"error": str(e)})
        logger.error(f"App command error: {e}")
        await message.reply("❌ Unable to launch app right now.")

# ==================== CHAT HANDLER ====================

async def chat_handler(message: types.Message):
    """Main chat handler with comprehensive monitoring"""
    user_id = message.from_user.id
    user_message = message.text
    
    # Determine user tier for monitoring
    user_tier = "free"
    try:
        status = await engine_client.get_user_status(str(user_id))
        user_tier = status.get("plan", "Free").lower()
    except Exception:
        pass
    
    async with monitor_request("bot_chat_message", user_id, user_tier):
        try:
            # Check rate limits
            if not await check_rate_limit(user_id, user_tier):
                await message.answer(
                    "⏰ You've reached your message limit. "
                    "Upgrade to premium for unlimited messages!"
                )
                log_user_action(user_id, "chat_rate_limited", False, {"tier": user_tier})
                return
            
            # Show typing indicator
            await message.bot.send_chat_action(message.chat.id, 'typing')
            
            # Get AI response
            start_time = time.time()
            
            try:
                if openai_client:
                    context = None
                    try:
                        # Fetch context via Engine API
                        context = await engine_client.get_chat_context(user_id)
                    except Exception as e:
                        logger.warning(f"Failed to fetch context: {e}")
                    
                    ai_response = await openai_client.get_chat_response(
                        user_id=user_id,
                        message=user_message,
                        context=context
                    )
                    
                    response_time = (time.time() - start_time) * 1000
                    
                    # Record AI response metrics
                    if prometheus:
                        prometheus.record_request("openai_api", "success", response_time / 1000, user_tier)
                        
                else:
                    # Fallback response if OpenAI not available
                    ai_response = (
                        "🤖 I'm currently processing your message. "
                        "For now, try using specific commands like /scan or /trending for memecoin analysis!"
                    )
                    response_time = (time.time() - start_time) * 1000
                
            except Exception as e:
                response_time = (time.time() - start_time) * 1000
                
                if prometheus:
                    prometheus.record_request("openai_api", "error", response_time / 1000, user_tier)
                
                logger.error(f"Chat AI error: {e}")
                await message.answer("🤖 Sorry, I'm having trouble processing your request. Please try again.")
                return
            
            # Save conversation to Engine API
            asyncio.create_task(
                engine_client.save_chat_message(
                    telegram_id=user_id,
                    user_message=user_message,
                    ai_response=ai_response
                )
            )
            
            # Send response
            await message.answer(ai_response)
            
            # Log successful chat interaction
            log_user_action(user_id, "chat_message", True, {
                "tier": user_tier,
                "message_length": len(user_message),
                "response_length": len(ai_response),
                "response_time_ms": response_time
            })
            
        except Exception as e:
            log_user_action(user_id, "chat_message", False, {
                "tier": user_tier,
                "error": str(e),
                "message_length": len(user_message) if user_message else 0
            })
            
            await message.answer(
                "❌ Something went wrong while processing your message. Please try again."
            )
            logger.error(f"Chat handler error: {e}")

@router.message()
async def handle_text_message(message: types.Message):
    """Handle non-command text messages"""
    # Skip if message is a command
    if message.text and message.text.startswith('/'):
        return
    
    # Handle as chat message
    await chat_handler_wrapper(message)

# ==================== REGISTRATION FUNCTIONS ====================

async def chat_handler_wrapper(message: types.Message):
    """Wrapper for chat handler"""
    await chat_handler(message)

def register_commands(dp, config=None, redis_client=None, db_manager=None):
    """Register all core commands - Compatible with aiogram 3.4.1"""
    try:
        # Include router in dispatcher (aiogram 3.x)
        dp.include_router(router)
        
        logger.info("✅ Core commands registered successfully with aiogram 3.4.1 (API-Only Mode)")
        return True
        
    except Exception as e:
        logger.error(f"Failed to register commands: {e}")
        return False