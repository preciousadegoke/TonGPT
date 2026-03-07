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
    """Startup handler with retry logic and error handling"""
    logger.info("🚀 TonGPT initialization starting...")
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # FIX-7: Use asyncio.create_task for the miniapp server
            logger.info("🌐 Starting Mini-App server task...")
            asyncio.create_task(
                start_miniapp_server_async(config),
                name="miniapp_server"
            )
            
            # FIX-10: Fix asyncio.wait_for Timeout to Use asyncio.timeout Context Manager
            logger.info("📦 Initializing services...")
            # Using wait_for + context guard pattern or explicit if pre-3.11,
            # but requirement specifies Python 3.11+ so asyncio.timeout is preferred.
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
            except (TimeoutError, asyncio.TimeoutError):
                 logger.error(f"Service initialization timed out (attempt {attempt + 1}/{max_retries})")
                 if attempt < max_retries - 1:
                     await _backoff(attempt)  # FIX-9
                 continue
            
            # FIX-3: Update global state to use ctx properties
            ctx.gpt_handler = services.get('gpt_handler')
            ctx.x_monitor = services.get('X_monitor') 
            
            # Initialize AdvancedRateLimiter so GPT/handlers can use create_rate_limit_decorator("ai_queries")
            try:
                from core.rate_limiting import get_rate_limiter
                get_rate_limiter(redis_client)
            except Exception as e:
                # FIX-1: Replace Any bare except/generalized logs with strongly typed e logging
                logger.warning(f"⚠️ Rate limiter (advanced) not initialized: {type(e).__name__}: {e}")
            
            # Start monitoring loop (Prometheus/metrics collection)
            try:
                from core.monitoring import monitoring_loop
                asyncio.create_task(monitoring_loop(60))
                logger.info("📊 Monitoring loop started (60s interval)")
            except Exception as e:
                 logger.warning(f"⚠️ Monitoring loop not started: {type(e).__name__}: {e}")
            
            # Register handlers after services are initialized
            logger.info("🔗 Registering handlers...")
            await register_all_handlers(ctx)  # FIX-6: Passes ctx
            
            # Set bot status in Redis (with fallback if Redis unavailable)
            # FIX-8: Replace naked Redis calls with safe_redis
            safe_redis("set", "bot_startup_time", int(time.time()))
            safe_redis("set", "bot_status", "online")
            
            logger.info("[Bot] TonGPT is now running with enhanced capabilities!")
            logger.info(f"[Web] Mini-App available at: http://localhost:{config.get('MINIAPP_PORT', 8000)}")
            return
            
        except Exception as e:
             # FIX-1: Already handled here with exc_info=True, just matching the style format
             logger.error(f"Service initialization failed (attempt {attempt + 1}/{max_retries}): {type(e).__name__}: {e}", exc_info=True)
             if attempt < max_retries - 1:
                  await _backoff(attempt)  # FIX-9
             else:
                  logger.critical("Failed to initialize TonGPT after max retries - shutting down")
                  raise

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
    ]
    
    registered, failed = [], []

    for module_name in HANDLER_MODULES:
        try:
            module = importlib.import_module(f'handlers.{module_name}')
            if hasattr(module, 'register'):
                module.register(ctx.dp, ctx)
                registered.append(module_name)
                logger.info(f"✅ Registered handler: {module_name}")
            elif hasattr(module, 'router'):
                ctx.dp.include_router(module.router)
                registered.append(module_name)
                logger.info(f"✅ Registered router: {module_name}")
            else:
                logger.warning(f"⚠️ No register() or router found in handlers.{module_name}")
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
        
        # Initialize bot
        await initialize_bot()
        
        # FIX-11: Add allowed_updates Comment and Guard
        # IMPORTANT: Update this list whenever a new handler type is added.
        # Omitting an update type here means Telegram will NOT send it — handlers will register but never fire.
        # Full list: https://core.telegram.org/bots/api#update
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