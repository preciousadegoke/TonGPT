import asyncio
import time
from datetime import datetime
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
from services.engine_client import engine_client, EngineServerError

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
import structlog
logger = structlog.get_logger(__name__)

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


def _is_valid_ton_address(address: str) -> bool:
    """Basic TON address validation.
    Valid formats:
      - User-friendly: starts with EQ or UQ, ~48 chars (base64url)
      - Raw hex: 64 hex chars (256-bit)
    """
    if not address:
        return False
    # User-friendly base64url format
    if address[:2] in ("EQ", "UQ") and 46 <= len(address) <= 50:
        return True
    # Raw hex format (workchain:hash)
    stripped = address.replace(":", "").replace("-", "")
    if len(stripped) == 64:
        try:
            int(stripped, 16)
            return True
        except ValueError:
            pass
    # Colon-separated format (e.g. 0:abcdef...)
    if ":" in address:
        parts = address.split(":", 1)
        if len(parts) == 2 and len(parts[1]) == 64:
            return True
    return False

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
    """Check if user has enough credits — fail-closed. Does NOT deduct."""
    if not redis_client:
        logger.warning("Redis unavailable — denying credit check (fail-closed)")
        return False
        
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
            
        return True
        
    except Exception as e:
        logger.error(f"Credit check error: {e}")
        return False  # Fail-closed: deny on error


async def deduct_user_credits(user_id, credits_needed=1):
    """Deduct credits after successful operation. Call only on confirmed success."""
    if not redis_client:
        return
    try:
        usage_key = f"usage_today:{user_id}"
        redis_client.incrby(usage_key, credits_needed)
    except Exception as e:
        logger.error(f"Credit deduction error: {e}")


async def refund_user_credits(user_id, credits_needed=1):
    """Refund credits on failure after deduction."""
    if not redis_client:
        return
    try:
        usage_key = f"usage_today:{user_id}"
        redis_client.decrby(usage_key, credits_needed)
    except Exception as e:
        logger.error(f"Credit refund error: {e}")

async def check_rate_limit(user_id, tier="free"):
    """Check user rate limits — fail-closed"""
    if not rate_limiter:
        logger.warning("Rate limiter unavailable — denying request (fail-closed)")
        return False
    
    try:
        is_limited, info = await rate_limiter.check_rate_limit(user_id, tier)
        return not is_limited
    except Exception as e:
        logger.error(f"Rate limit check error: {e}")
        return False  # Fail-closed: deny on error

async def log_user_action(user_id, action, success=True, metadata=None):
    """Safe async logging wrapper using EngineClient."""
    await engine_client.log_activity(
        user_id,
        action,
        {"success": success, **(metadata or {})},
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

    # ── Parse deep-link referral payload (/start ref_XXXX_YYYY) ──
    try:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) > 1 and parts[1].startswith("ref_"):
            ref_token = parts[1][4:]  # strip "ref_" prefix
            from handlers.referral import verify_referral_token, record_referral_source
            referrer_id = verify_referral_token(ref_token)
            if referrer_id and referrer_id != user_id:  # Prevent self-referral
                await record_referral_source(user_id, referrer_id)
                logger.info(f"Referral accepted: user {user_id} referred by {referrer_id}")
            elif referrer_id == user_id:
                logger.warning(f"Self-referral attempt blocked for user {user_id}")
    except Exception as e:
        logger.warning(f"Referral parsing failed (non-fatal): {e}")
    
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
        logger.error(f"Start command error for user {user_id}: {e}")
        await message.answer("❌ Sorry, something went wrong. Please try again later.")

@router.message(Command("help"))
@monitor_function("bot_command_help")
async def help_command(message: types.Message, **kwargs):
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
        
        "🔒 <b>Privacy (GDPR):</b>\n"
        "• /export - Download your data\n"
        "• /deletedata - Delete your data\n\n"
        
        "🎯 <b>Focus:</b> Pure TON memecoins only - no major cryptos!\n"
        "💡 <b>Tip:</b> Free plan includes 100 credits/month"
    )

    await message.reply(help_text, parse_mode="HTML")
    await log_user_action(user_id, "help_command", True)

@router.message(Command("export"))
async def export_data_command(message: types.Message):
    """Export user data (GDPR data portability)."""
    user_id = message.from_user.id
    try:
        data = await engine_client.export_user_data(user_id)
        if not data:
            await message.reply("❌ No data found or service unavailable.")
            return
        import json
        # Send as file if large, else as message
        payload = json.dumps(data, indent=2, default=str)
        if len(payload) > 3500:
            from aiogram.types import BufferedInputFile
            file = BufferedInputFile(file=payload.encode("utf-8"), filename="tongpt_export.json")
            await message.reply_document(
                document=file,
                caption="📦 Your TonGPT data export. See PRIVACY.md for how we use data."
            )
        else:
            await message.reply(
                f"<pre>{payload[:3500]}</pre>\n\n📄 Full export available in repo PRIVACY.md.",
                parse_mode="HTML"
            )
        await log_user_action(user_id, "export_data", True)
    except Exception as e:
        logger.error(f"Export data error: {e}")
        await message.reply("❌ Could not export data. Please try again later.")
        await log_user_action(user_id, "export_data", False, {"error": str(e)})

@router.message(Command("deletedata"))
async def delete_data_command(message: types.Message):
    """Delete or anonymize user data (GDPR right to erasure)."""
    user_id = message.from_user.id
    try:
        ok = await engine_client.delete_user_data(user_id)
        if ok:
            await message.reply(
                "✅ Your data has been deleted or anonymized. "
                "We may retain minimal records required by law (e.g. payment audit). "
                "You can keep using the bot; a new record will be created if you use /start again."
            )
            await log_user_action(user_id, "delete_data", True)
        else:
            await message.reply("❌ Could not complete deletion. Please try again or contact support.")
            await log_user_action(user_id, "delete_data", False)
    except Exception as e:
        logger.error(f"Delete data error: {e}")
        await message.reply("❌ Could not delete data. Please try again later.")
        await log_user_action(user_id, "delete_data", False, {"error": str(e)})

@router.message(Command("accept_terms"))
async def accept_terms_command(message: types.Message):
    """Accept Terms of Service and Privacy Policy"""
    CURRENT_TOS_VERSION = "1.0"
    user_id = message.from_user.id
    try:
        from utils.redis_conn import redis_client
        if redis_client:
            redis_client.set(f"terms_accepted:{user_id}", CURRENT_TOS_VERSION)
            
        await message.reply(
            f"✅ <b>Terms Accepted (v{CURRENT_TOS_VERSION})!</b>\n\n"
            "Thank you for accepting the TonGPT Terms of Service and Privacy Policy.\n"
            "You can now use all features of the bot. Try /scan or /ask to get started!",
            parse_mode="HTML"
        )
        await log_user_action(user_id, "accept_terms", True, {"version": CURRENT_TOS_VERSION})
    except Exception as e:
        logger.error(f"Error accepting terms: {e}")
        await message.reply("❌ An error occurred. Please try again later.")

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
            
            await log_user_action(user_id, "scan_command", True, {
                "tier": user_tier,
                "tokens_found": len(memecoins),
                "response_time_ms": response_time
            })
                
        except Exception as e:
            await log_user_action(user_id, "scan_command", False, {"tier": user_tier, "error": str(e)})
            logger.error(f"Error in scan command: {e}")
            await message.reply("❌ Scan service temporarily unavailable.")

# NOTE: /ask command handler has been REMOVED from bot/commands.py (C-1 fix)
# All GPT reply routing lives exclusively in handlers/gpt_reply.py
# This prevents dual router conflicts (double responses, double AI calls)

@router.message(Command("info"))
@monitor_function("bot_command_info")
async def info_command(message: types.Message, **kwargs):
    """Enhanced info command with monitoring, address validation, and better error handling"""
    user_id = message.from_user.id
    
    try:
        if not message.text:
            await message.reply("❌ Usage: /info <contract_address>")
            return
        
        command_text = message.text.replace("/info", "", 1).strip()
        args = command_text.split() if command_text else []
        
        if not args:
            await message.reply(
                "❌ <b>Usage:</b> /info <code>&lt;contract_address&gt;</code>\n\n"
                "💡 <b>Example:</b>\n"
                "<code>/info EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT</code>\n\n"
                "Accepts EQ.../UQ... or raw hex addresses.",
                parse_mode="HTML"
            )
            return
            
        contract = args[0]

        # P0-FIX: Validate address format before hitting the API
        if not _is_valid_ton_address(contract):
            await message.reply(
                "❌ <b>Invalid contract address format</b>\n\n"
                f"Received: <code>{contract[:60]}</code>\n\n"
                "💡 TON addresses should:\n"
                "• Start with <code>EQ</code> or <code>UQ</code> (~48 chars), or\n"
                "• Be a raw hex hash (64 hex characters)\n\n"
                "Example: <code>/info EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT</code>",
                parse_mode="HTML"
            )
            return
        
        start_time = time.time()
        
        try:
            data = await get_token_info_from_tonviewer(contract)
            response_time = (time.time() - start_time) * 1000
            
            if prometheus:
                prometheus.record_request("tonviewer_api", "success", response_time / 1000)
            
            if not data:
                logger.warning("token_info_empty", contract=contract, response_time_ms=response_time)
                await message.reply(
                    "❌ <b>Token not found</b>\n\n"
                    f"Contract: <code>{contract}</code>\n\n"
                    "Possible reasons:\n"
                    "• Address is not a Jetton contract\n"
                    "• Token not yet indexed by TonAPI\n"
                    "• Address is a wallet, not a token\n\n"
                    "💡 Try copying the address from a DEX or explorer.",
                    parse_mode="HTML"
                )
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
            
            await log_user_action(user_id, "info_command", True, {
                "contract": contract,
                "response_time_ms": response_time
            })
            
        except Exception as api_error:
            response_time = (time.time() - start_time) * 1000
            
            if prometheus:
                prometheus.record_request("tonviewer_api", "error", response_time / 1000)
            
            logger.error("token_info_api_error", contract=contract, err=f"{type(api_error).__name__}: {api_error}", response_time_ms=response_time)
            await message.reply(
                "❌ <b>Unable to fetch token information</b>\n\n"
                f"Contract: <code>{contract}</code>\n"
                f"Error: <code>{type(api_error).__name__}</code>\n\n"
                "Please try again in a few moments.",
                parse_mode="HTML"
            )
            
    except Exception as e:
        await log_user_action(user_id, "info_command", False, {"error": str(e)})
        logger.error("info_command_error", err=str(e))
        await message.reply("❌ An error occurred.")

@router.message(Command("trending"))
@monitor_function("bot_command_trending")
async def trending_command(message: types.Message, **kwargs):
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
        
        await log_user_action(user_id, "trending_command", True, {"memecoins_analyzed": len(memecoins)})
        
    except Exception as e:
        await log_user_action(user_id, "trending_command", False, {"error": str(e)})
        logger.error(f"Error in trending command: {e}")
        await message.reply("❌ Unable to analyze trends.")

# ==================== SUBSCRIPTION COMMANDS ====================

# NOTE: /subscription and /sub handlers REMOVED from bot/commands.py (P0-FIX-3)
# The canonical handler lives in handlers/subscription_handler.py which registers
# Command("subscription", "sub") and Command("upgrade"). Having them in both files
# caused duplicate messages because the router was included twice.

# ==================== SOCIAL & UTILITY COMMANDS ====================

@router.message(Command("app"))
@monitor_function("bot_command_app")
async def open_app_command(message: types.Message, **kwargs):
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
        await log_user_action(user_id, "open_app", True)
        
    except Exception as e:
        await log_user_action(user_id, "open_app", False, {"error": str(e)})
        logger.error(f"App command error: {e}")
        await message.reply("❌ Unable to launch app right now.")

# ==================== STUB COMMANDS (referenced in /help) ====================

@router.message(Command("stats"))
async def stats_command(message: types.Message, **kwargs):
    """Show basic user stats — queries used, plan, member since"""
    user_id = message.from_user.id

    plan = "Free"
    queries_today = 0
    member_since = "N/A"

    # 1. Try Engine first
    try:
        status_data = await engine_client.get_user_status(str(user_id))
        plan = (status_data.get("plan") or "Free").title()
        member_since = status_data.get("created_at", "N/A")
        if member_since and member_since != "N/A":
            try:
                dt = datetime.fromisoformat(str(member_since).replace("Z", "+00:00"))
                member_since = dt.strftime("%Y-%m-%d")
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"Engine unavailable for /stats: {e}")

    # 2. Fallback to Redis for usage count
    try:
        if redis_client:
            usage = redis_client.get(f"usage_today:{user_id}")
            queries_today = int(usage) if usage else 0
    except Exception as e:
        logger.debug(f"Redis unavailable for /stats: {e}")

    # 3. Live AI-query quota usage from the canonical rate limiter (read-only).
    quota_text = ""
    try:
        from core.rate_limiter import get_rate_limiter
        limiter = get_rate_limiter()
        if limiter:
            q = await limiter.get_quota_status(user_id, plan.lower(), "ai_queries")
            windows = q.get("windows", {})
            lines = []
            for label, key in (("This minute", "minute"), ("This hour", "hour"), ("Today", "day")):
                w = windows.get(key)
                if w:
                    lines.append(f"  • {label}: {w['used']}/{w['limit']}")
            if lines:
                header = "🧮 <b>AI Quota Usage</b>"
                if q.get("degraded"):
                    header += " <i>(safe mode)</i>"
                quota_text = "\n" + header + "\n" + "\n".join(lines) + "\n"
    except Exception as e:
        logger.debug(f"Quota status unavailable for /stats: {e}")

    stats_text = (
        f"📊 <b>Your Stats</b>\n\n"
        f"👤 <b>User ID:</b> {user_id}\n"
        f"📋 <b>Plan:</b> {plan}\n"
        f"🔢 <b>Queries Today:</b> {queries_today}\n"
        f"📅 <b>Member Since:</b> {member_since}\n"
        f"{quota_text}\n"
        f"💡 Use /subscription for full plan details"
    )

    await message.reply(stats_text, parse_mode="HTML")
    await log_user_action(user_id, "stats_command", True)


@router.message(Command("support"))
async def support_command(message: types.Message, **kwargs):
    """Send support contact information"""
    support_text = (
        "🛟 <b>TonGPT Support</b>\n\n"
        "Need help? Reach us through any of these channels:\n\n"
        "💬 <b>Telegram:</b> @TonGPT_Support\n"
        "📧 <b>Email:</b> support@tongpt.io\n\n"
        "🕐 <b>Response Time:</b> Usually within 24 hours\n"
        "📋 <b>When contacting us, include:</b>\n"
        f"• Your User ID: <code>{message.from_user.id}</code>\n"
        "• A description of the issue\n"
        "• Any error messages you received\n\n"
        "💎 Premium users get priority support!"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Contact Support", url="https://t.me/TonGPT_Support")]
    ])

    await message.reply(support_text, parse_mode="HTML", reply_markup=keyboard)


@router.message(Command("join"))
async def join_command(message: types.Message, **kwargs):
    """Send community links"""
    join_text = (
        "🌐 <b>Join the TonGPT Community</b>\n\n"
        "Connect with fellow TON memecoin enthusiasts:\n\n"
        "📢 <b>Announcements:</b> @TonGPT_News\n"
        "💬 <b>Discussion Group:</b> @TonGPT_Community\n"
        "🐦 <b>Twitter/X:</b> @TonGPT_io\n\n"
        "🎁 <b>Community Benefits:</b>\n"
        "• Early access to new features\n"
        "• Exclusive alpha signals\n"
        "• Direct feedback to the dev team\n"
        "• Community-driven token analysis\n\n"
        "🚀 Join now and stay ahead of the market!"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📢 Channel", url="https://t.me/TonGPT_News"),
            InlineKeyboardButton(text="💬 Group", url="https://t.me/TonGPT_Community"),
        ]
    ])

    await message.reply(join_text, parse_mode="HTML", reply_markup=keyboard)


@router.message(Command("alert"))
async def alert_command(message: types.Message, **kwargs):
    """Price alert entry point — delegates to handlers/alerts.py if wired, else stub"""
    # handlers/alerts.py has a full FSM-based alert flow registered via
    # register_alerts_handlers(dp) which listens on /alerts (plural).
    # This /alert (singular) command provides a friendly redirect.
    alert_text = (
        "🔔 <b>Price Alerts</b>\n\n"
        "Set custom price alerts for any TON token!\n\n"
        "📌 <b>How to use:</b>\n"
        "• /alerts — Start the alert setup wizard\n"
        "  (enter a token symbol, then a target price)\n\n"
        "⚙️ <b>Features:</b>\n"
        "• Supports any TON jetton\n"
        "• Alerts stored in Redis for fast checks\n"
        "• Notifications via bot message\n\n"
        "💎 Premium users get unlimited alerts!"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔔 Set an Alert", callback_data="start_alert_setup")],
        [InlineKeyboardButton(text="💎 Upgrade for More", callback_data="pay_ton")]
    ])

    await message.reply(alert_text, parse_mode="HTML", reply_markup=keyboard)


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
                await log_user_action(user_id, "chat_rate_limited", False, {"tier": user_tier})
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
                    except EngineServerError:
                        context = []
                        logger.warning("Engine unavailable — chat context temporarily missing for user %s", user_id)
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
            await log_user_action(user_id, "chat_message", True, {
                "tier": user_tier,
                "message_length": len(user_message),
                "response_length": len(ai_response),
                "response_time_ms": response_time
            })
            
        except Exception as e:
            await log_user_action(user_id, "chat_message", False, {
                "tier": user_tier,
                "error": str(e),
                "message_length": len(user_message) if user_message else 0
            })
            
            await message.answer(
                "❌ Something went wrong while processing your message. Please try again."
            )
            logger.error(f"Chat handler error: {e}")

# NOTE: Catch-all @router.message() handler has been REMOVED from bot/commands.py (C-1 fix)
# All non-command message handling lives exclusively in handlers/gpt_reply.py
# This prevents dual router conflicts (double responses, double AI calls)

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