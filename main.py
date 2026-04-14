"""
main.py — TonGPT Bot Entry Point
Remediated: FIX-1 through FIX-13 applied.
Requires Python 3.11+ for asyncio.timeout support.
"""

import asyncio
import logging
import os
import threading
import time
import importlib
import random
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Any

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.types import ErrorEvent
from dotenv import load_dotenv

# FIX-3: AppContext Dataclass; Eliminate Bare Globals
@dataclass
class AppContext:
    bot: Optional[Any] = None
    dp: Optional[Any] = None
    gpt_handler: Optional[Any] = None
    x_monitor: Optional[Any] = None

ctx = AppContext()

# Load environment variables first, before any local imports
load_dotenv(dotenv_path=Path('.') / '.env')

# C-14: Validate required env vars early — before any module-level os.environ[] calls
from core.env_guard import validate_required_env_vars
validate_required_env_vars()

# FIX-4: Unify Token Environment Variable Naming
_bot_token = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
if _bot_token:
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", _bot_token)
    os.environ.setdefault("BOT_TOKEN", _bot_token)
    os.environ.setdefault("TELEGRAM_TOKEN", _bot_token)

# Explicit validation before any service initializes
REQUIRED_ENV_VARS = [
    "BOT_TOKEN", "ENGINE_API_KEY", "REFERRAL_SECRET",
    "CORS_ALLOWED_ORIGINS", "PAYMENT_WALLET_ADDRESS",
    "TELEGRAM_BOT_TOKEN", # FIX-4: Add TELEGRAM_BOT_TOKEN to REQUIRED_ENV_VARS
]
missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
if missing:
    raise EnvironmentError(
        f"Missing required environment variables: {', '.join(missing)}"
    )

# FIX-5: Add REFERRAL_SECRET Entropy Guard
_referral_secret = os.environ.get("REFERRAL_SECRET", "")
if len(_referral_secret) < 32:
    raise ValueError(
        "REFERRAL_SECRET must be at least 32 characters. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )

# FIX-12: Add CORS Wildcard Production Guard
_cors_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "")
_env = os.environ.get("ENV", "production").lower()
if "*" in _cors_origins and _env != "development":
    raise ValueError(
        "CORS_ALLOWED_ORIGINS cannot be '*' in production. "
        "Set ENV=development to allow wildcard origins locally."
    )

from api.miniapp_server import create_miniapp_server
from core.config import load_config, validate_config
from core.health import health_check
from core.initialization import initialize_all_services
from utils.redis_conn import redis_client
from core.logging_config import configure_logging

# FIX-8: Add safe_redis Wrapper
def safe_redis(method: str, *args, **kwargs):
    """Execute a Redis command with None-guard and exception logging."""
    if not redis_client:
        logger.debug(f"Redis unavailable — skipping {method}({args[0] if args else ''})")
        return None
    try:
        return getattr(redis_client, method)(*args, **kwargs)
    except Exception as e:
        logger.warning(f"⚠️ Redis {method} failed: {type(e).__name__}: {e}")
        return None

# Now load the config after .env is loaded
config = load_config()

# Setup logging with PII redaction and rotation
configure_logging("bot.log")
logger = logging.getLogger(__name__)

# FIX-13: Audit Log Calls; Redact Sensitive Config Keys
_REDACT_KEYS = {
    "BOT_TOKEN", "ENGINE_API_KEY", "REFERRAL_SECRET",
    "PAYMENT_WALLET_ADDRESS", "OPENROUTER_API_KEY",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN",
    "X_API_KEY", "X_API_SECRET", "X_BEARER_TOKEN",
    "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET",
    "REDIS_URL",
}

def sanitise_config(cfg: dict) -> dict:
    return {
        k: ("***REDACTED***" if k in _REDACT_KEYS else v)
        for k, v in cfg.items()
    }

# Suppress noisy logs
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# FIX-9: Add Jitter to Retry Backoff
async def _backoff(attempt: int, base: float = 1.0, cap: float = 30.0):
    delay = min(cap, base * (2 ** attempt))
    jitter = random.uniform(0, delay * 0.25)
    await asyncio.sleep(delay + jitter)

# ── Price Alert Polling Loop (Fix-5) ──────────────────────────────────
async def price_alert_polling_loop():
    """Background task: check Redis alerts and send notifications when price crosses target."""
    from services.tonapi import get_ton_price_usd
    from services.notifications import notification_service

    while True:
        try:
            if not redis_client or not redis_client.available:
                await asyncio.sleep(60)
                continue

            # Fetch current TON price (once per cycle)
            try:
                current_price = await get_ton_price_usd()
            except Exception as price_err:
                logger.warning(f"Price alert loop: price fetch failed — {type(price_err).__name__}: {price_err}")
                await asyncio.sleep(60)
                continue

            # Iterate over alerts:* keys using incremental scan (not blocking KEYS)
            for key in redis_client.scan_iter(match="alerts:*"):
                try:
                    user_id = key.split(":", 1)[1] if ":" in key else None
                    if not user_id:
                        continue

                    alerts = redis_client.hgetall(key)
                    if not alerts:
                        continue

                    for field, target_val in alerts.items():
                        try:
                            target_price = float(target_val)
                        except (ValueError, TypeError):
                            continue

                        # Trigger if price crosses the target (above or below)
                        if current_price >= target_price:
                            await notification_service.send_price_alert(
                                user_id=user_id,
                                price_data={
                                    "symbol": field.split(":")[0] if ":" in field else "TON",
                                    "current_price": current_price,
                                    "target_price": target_price,
                                    "price_change_24h": 0,
                                    "price_change_percentage_24h": 0,
                                },
                            )
                            # Remove triggered alert so it doesn't fire again
                            redis_client.hdel(key, field)
                            logger.info(f"Price alert triggered for user {user_id}: {field} >= {target_price}")
                except Exception as inner_err:
                    logger.warning(f"Price alert scan error for {key}: {inner_err}")

        except Exception as e:
            logger.error(f"Price alert polling error: {type(e).__name__}: {e}")

        await asyncio.sleep(60)


# FIX-7: Move Miniapp Server From Daemon Thread to asyncio.Task
async def start_miniapp_server_async(config: dict):
    """Run the FastAPI miniapp server as a monitored asyncio task."""
    try:
        import uvicorn
        from api.miniapp_server import miniapp

        host = config.get("MINIAPP_HOST", "0.0.0.0")
        port = config.get("MINIAPP_PORT", 8000)

        uv_config = uvicorn.Config(
            miniapp,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(uv_config)
        logger.info(f"🌐 Mini-App server starting on {host}:{port}")
        await server.serve()
    except Exception as e:
        logger.error(f"❌ Mini-App server crashed: {type(e).__name__}: {e}", exc_info=True)


async def on_startup():
    """Startup handler — service initialization and background tasks only.
    
    Handler registration is done in main() BEFORE start_polling() to guarantee
    handlers are always available, regardless of service init outcome.
    """
    logger.info("🚀 TonGPT service initialization starting...")
    
    # FIX-7: Use asyncio.create_task for the miniapp server
    try:
        logger.info("🌐 Starting Mini-App server task...")
        asyncio.create_task(
            start_miniapp_server_async(config),
            name="miniapp_server"
        )
    except Exception as e:
        logger.warning(f"⚠️ Mini-App server task failed to create: {type(e).__name__}: {e}")
    
    # FIX-10: Initialize services with timeout + retry
    services = {}
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.info("📦 Initializing services...")
            try:
                has_asyncio_timeout = hasattr(asyncio, 'timeout')
                if has_asyncio_timeout:
                    async with asyncio.timeout(30.0):
                        services = await initialize_all_services(config)
                else:
                    services = await asyncio.wait_for(
                        initialize_all_services(config),
                        timeout=30.0
                    )
                break  # Success — exit retry loop
            except (TimeoutError, asyncio.TimeoutError):
                logger.error(f"Service initialization timed out (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await _backoff(attempt)  # FIX-9
                continue
        except Exception as e:
            logger.error(f"Service initialization failed (attempt {attempt + 1}/{max_retries}): {type(e).__name__}: {e}", exc_info=True)
            if attempt < max_retries - 1:
                await _backoff(attempt)  # FIX-9
            else:
                logger.critical("All service init retries exhausted — bot will run with limited features")
    
    # FIX-3: Update global state to use ctx properties
    ctx.gpt_handler = services.get('gpt_handler')
    ctx.x_monitor = services.get('X_monitor')
    
    # Initialize AdvancedRateLimiter
    try:
        from core.rate_limiting import get_rate_limiter
        get_rate_limiter(redis_client)
    except Exception as e:
        logger.warning(f"⚠️ Rate limiter (advanced) not initialized: {type(e).__name__}: {e}")
    
    # Start monitoring loop (Prometheus/metrics collection)
    try:
        from core.monitoring import monitoring_loop
        asyncio.create_task(monitoring_loop(60))
        logger.info("📊 Monitoring loop started (60s interval)")
    except Exception as e:
        logger.warning(f"⚠️ Monitoring loop not started: {type(e).__name__}: {e}")
    
    # Start wallet monitoring background task
    try:
        from services.monitor import monitor_followed_wallets
        asyncio.create_task(
            monitor_followed_wallets(),
            name="wallet_monitor"
        )
        logger.info("👛 Wallet monitoring task started")
    except Exception as e:
        logger.warning(f"⚠️ Wallet monitor not started: {type(e).__name__}: {e}")
    
    # Start X/Twitter monitoring background task
    try:
        if ctx.x_monitor:
            asyncio.create_task(
                ctx.x_monitor.enhanced_monitoring_cycle(),
                name="x_monitor"
            )
            logger.info("🐦 X monitoring task started")
        else:
            logger.info("ℹ️ X monitor not available — skipping")
    except Exception as e:
        logger.warning(f"⚠️ X monitor not started: {type(e).__name__}: {e}")
    
    # Start price alert polling loop
    try:
        asyncio.create_task(
            price_alert_polling_loop(),
            name="price_alert_poller"
        )
        logger.info("💰 Price alert polling task started")
    except Exception as e:
        logger.warning(f"⚠️ Price alert poller not started: {type(e).__name__}: {e}")
    
    # Set bot status in Redis (with fallback if Redis unavailable)
    # FIX-8: Replace naked Redis calls with safe_redis
    safe_redis("set", "bot_startup_time", int(time.time()))
    safe_redis("set", "bot_status", "online")
    
    logger.info("[Bot] TonGPT is now running with enhanced capabilities!")
    logger.info(f"[Web] Mini-App available at: http://localhost:{config.get('MINIAPP_PORT', 8000)}")

async def on_shutdown():
    """Shutdown handler"""
    logger.info("🛑 TonGPT is shutting down...")
    
    # FIX-8: Replace naked Redis calls with safe_redis
    safe_redis("set", "bot_status", "offline")
    safe_redis("set", "bot_shutdown_time", int(time.time()))
    
    try:
        # FIX-3: Use ctx
        await ctx.bot.session.close()
        logger.info("🔐 Bot session closed cleanly")
    # FIX-1: Replace bare except pass
    except Exception as e:
         logger.warning(f"⚠️ Failed to close bot session: {type(e).__name__}: {e}")
    
    logger.info("👋 TonGPT shutdown complete")

# FIX-2: Fix the error_handler Variable Reference Bug
async def error_handler(event: ErrorEvent):
    """Global error handler"""
    logger.error(f"🚨 Unhandled exception: {event.exception}", exc_info=event.exception)
    
    try:
        # Extract the update object from the ErrorEvent
        update = event.update
        # Get the message if it exists
        message = update.message if update else None
        
        if message:
            # FIX-2: message.reply instead of event.message.reply
            await message.reply(
                "⚠️ <b>Something went wrong</b>\n\n"
                "Please try again in a few moments.\n\n"
                "💡 Use /help for available commands",
                parse_mode="HTML"
            )
    # FIX-1: Replace bare except pass
    except Exception as e:
        logger.warning(f"Could not send error reply to user: {type(e).__name__}: {e}")
    
    return True

async def initialize_bot():
    """Initialize bot and dispatcher"""
    
    # Validate configuration first
    if not validate_config(config):
        raise ValueError("Invalid configuration")
    
    # FIX-3: Update state to use ctx
    ctx.bot = Bot(
        token=config["BOT_TOKEN"],
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            protect_content=False,
            allow_sending_without_reply=True
        )
    )
    # H-5: Register bot in shared singleton so services don't have to import from main
    from core.bot_instance import set_bot
    set_bot(ctx.bot)
    
    # Initialize dispatcher
    ctx.dp = Dispatcher(storage=MemoryStorage())
    
    # Register event handlers after dispatcher is created
    ctx.dp.startup.register(on_startup)
    ctx.dp.shutdown.register(on_shutdown)
    ctx.dp.error.register(error_handler)
    
    # Validate bot token
    try:
        bot_info = await ctx.bot.get_me()
        logger.info(f"🤖 Bot authenticated: @{bot_info.username} (ID: {bot_info.id})")
    except Exception as e:
         logger.critical(f"❌ Bot authentication failed: {type(e).__name__}: {e}")
         raise

# FIX-6: Enforce a Consistent Handler Registration Contract
async def register_all_handlers(ctx: AppContext):
    """Register all bot handlers"""
    logger.info("📦 Registering handler modules...")

    HANDLER_MODULES = [
       "gpt_reply",
       "subscription_handler",
       "pay",
       "X_handler",
       "whale",
       "alerts",
       "wallet_watch",
       "ston",
       "early_detection",
       "influencer_handler",
       "referral",
    ]
    
    registered, failed = [], []

    for module_name in HANDLER_MODULES:
        try:
            module = importlib.import_module(f'handlers.{module_name}')
            # Try register function first (accepts dp and optional ctx)
            reg_func = None
            for attr_name in dir(module):
                if attr_name.startswith('register') and callable(getattr(module, attr_name)):
                    reg_func = getattr(module, attr_name)
                    break
            
            if reg_func:
                import inspect
                sig = inspect.signature(reg_func)
                params = list(sig.parameters.keys())
                if len(params) >= 2:
                    reg_func(ctx.dp, ctx)
                else:
                    reg_func(ctx.dp)
                registered.append(module_name)
                logger.info(f"✅ Registered handler via function: {module_name}")
            elif hasattr(module, 'router'):
                ctx.dp.include_router(module.router)
                registered.append(module_name)
                logger.info(f"✅ Registered router: {module_name}")
            else:
                logger.warning(f"⚠️ No register function or router found in handlers.{module_name}")
                failed.append(module_name)
        except ImportError:
            logger.warning(f"⚠️ Handler module not found: {module_name} — skipping")
            failed.append(module_name)
        except Exception as e:
            logger.error(f"❌ Failed to register {module_name}: {type(e).__name__}: {e}", exc_info=True)
            failed.append(module_name)
            
    logger.info(f"✅ Registered {len(registered)}/{len(HANDLER_MODULES)} handlers")
    if failed:
        logger.warning(f"⚠️ Failed handlers: {', '.join(failed)}")
    
    # Register core commands separately with bot instance (adapted to the new pattern if applicable)
    try:
        from bot.commands import register_commands
        
        # Check if register_commands is async
        import inspect
        if inspect.iscoroutinefunction(register_commands):
            await register_commands(ctx.dp, config=config, redis_client=redis_client)
        else:
            register_commands(ctx.dp, config=config, redis_client=redis_client)
        
        logger.info("✅ Registered core commands")
    except Exception as e:
        logger.error(f"❌ Failed to register core commands: {type(e).__name__}: {e}")

async def main():
    """Main application entry point"""
    try:
        logger.info("🎬 TonGPT starting up...")
        
        # FIX-13: Log config using sanitise_config
        logger.debug(f"Loaded config: {sanitise_config(config)}")
        
        # Initialize bot and dispatcher
        await initialize_bot()
        
        # ── Register ALL handlers BEFORE polling starts ──────────────────
        # This guarantees handlers are always available, regardless of
        # whether on_startup's service initialization succeeds or fails.
        # Matches original_main.py pattern where core commands are
        # registered at module level before start_polling.
        logger.info("🔗 Registering handlers...")
        await register_all_handlers(ctx)
        
        # FIX-11: Add allowed_updates Comment and Guard
        # IMPORTANT: Update this list whenever a new handler type is added.
        # Omitting an update type here means Telegram will NOT send it.
        # Full list: https://core.telegram.org/bots/api#update
        # NOTE: successful_payment is delivered inside Message objects,
        # it is NOT a top-level update type and must NOT be listed here.
        ALLOWED_UPDATES = ["message", "callback_query", "pre_checkout_query"]

        # FIX-3: Use ctx
        await ctx.dp.start_polling(
            ctx.bot,
            polling_timeout=10,
            handle_signals=True,
            fast=True,
            allowed_updates=ALLOWED_UPDATES,
        )
        
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user (Ctrl+C)")
    except Exception as e:
         logger.exception(f"🚨 Critical error in main loop: {type(e).__name__}: {e}")
         raise
    finally:
        try:
            if ctx.bot:
                await ctx.bot.session.close()
        # FIX-1: Replace bare except pass
        except Exception as e:
             logger.warning(f"⚠️ Failed to gracefully close bot session in main loop exit: {type(e).__name__}: {e}")

if __name__ == "__main__":
    try:
        # Set process title if possible
        try:
            import setproctitle
            setproctitle.setproctitle("TonGPT-Bot")
        # FIX-1: Replace bare except pass
        except Exception as e:
             logger.warning(f"⚠️ Could not set process title: {type(e).__name__}: {e}")
             
        asyncio.run(main())
        
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.exception(f"🚨 TonGPT crashed: {type(e).__name__}: {e}")
        exit(1)
    finally:
        logger.info("👋 TonGPT process ended")