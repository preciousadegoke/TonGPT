import asyncio
import logging
import os
import threading
import time
import importlib
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

from api.miniapp_server import create_miniapp_server
from core.config import load_config, validate_config
from core.health import health_check
from core.initialization import initialize_all_services
from utils.redis_conn import redis_client

# Load environment variables first
load_dotenv(dotenv_path=Path('.') / '.env')

# Now load the config after .env is loaded
config = load_config()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Suppress noisy logs
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# Global service instances
bot = None
dp = None
gpt_handler = None
X_monitor = None
# subscription_manager = None
miniapp_server = None

async def on_startup():
    """Startup handler with retry logic and error handling"""
    logger.info("🚀 TonGPT initialization starting...")
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Start mini-app server in background
            logger.info(f"🌐 Starting Mini-App server...")
            api_thread = threading.Thread(target=start_miniapp_server, daemon=True)
            api_thread.daemon = True
            api_thread.start()
            
            # Initialize all services with timeout
            logger.info("📦 Initializing services...")
            services = await asyncio.wait_for(
                initialize_all_services(config),
                timeout=30.0
            )
            
            # Set global references
            global gpt_handler, X_monitor
            gpt_handler = services.get('gpt_handler')
            X_monitor = services.get('X_monitor') 
            
            # Register handlers after services are initialized
            logger.info("🔗 Registering handlers...")
            await register_all_handlers()
            
            # Subscription manager linking - REMOVED (Handled via C# Engine)
            
            # Set bot status in Redis (with fallback if Redis unavailable)
            try:
                if redis_client:
                    redis_client.set("bot_startup_time", int(time.time()))
                    redis_client.set("bot_status", "online")
            except Exception as e:
                logger.warning(f"⚠️ Redis status update failed: {e}")
            
            logger.info("🤖 TonGPT is now running with enhanced capabilities!")
            logger.info(f"🌐 Mini-App available at: http://localhost:{config.get('MINIAPP_PORT', 8000)}")
            return
            
        except asyncio.TimeoutError:
            logger.error(f"Service initialization timeout (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
        except Exception as e:
            logger.error(f"Service initialization failed (attempt {attempt + 1}/{max_retries}): {e}", exc_info=True)
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                logger.critical("Failed to initialize TonGPT after max retries - shutting down")
                raise

async def on_shutdown():
    """Shutdown handler"""
    logger.info("🛑 TonGPT is shutting down...")
    
    try:
        redis_client.set("bot_status", "offline")
        redis_client.set("bot_shutdown_time", int(time.time()))
    except Exception as e:
        logger.warning(f"⚠ Redis status update failed: {e}")
    
    try:
        await bot.session.close()
        logger.info("🔐 Bot session closed cleanly")
    except:
        pass
    
    logger.info("👋 TonGPT shutdown complete")

async def error_handler(event, exception):
    """Global error handler"""
    logger.error(f"🚨 Unhandled exception: {exception}")
    
    try:
        if hasattr(event, 'message') and event.message:
            await event.message.reply(
                "⚠️ <b>Something went wrong</b>\n\n"
                "Please try again in a few moments.\n\n"
                "💡 Use /help for available commands",
                parse_mode="HTML"
            )
    except:
        pass
    
    return True

async def initialize_bot():
    """Initialize bot and dispatcher"""
    global bot, dp
    
    # Validate configuration first
    if not validate_config(config):
        raise ValueError("Invalid configuration")
    
    # Initialize bot
    bot = Bot(
        token=config["BOT_TOKEN"],
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            protect_content=False,
            allow_sending_without_reply=True
        )
    )
    
    # Initialize dispatcher
    dp = Dispatcher(storage=MemoryStorage())
    
    # Register event handlers after dispatcher is created
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    dp.error.register(error_handler)
    
    # Validate bot token
    try:
        bot_info = await bot.get_me()
        logger.info(f"🤖 Bot authenticated: @{bot_info.username} (ID: {bot_info.id})")
    except Exception as e:
        logger.critical(f"❌ Bot authentication failed: {e}")
        raise

def start_miniapp_server():
    """Start the FastAPI server for mini-app in a separate thread"""
    try:
        import uvicorn
        from api.miniapp_server import miniapp
        
        uvicorn.run(
            miniapp,
            host=config.get("MINIAPP_HOST", "0.0.0.0"),
            port=config.get("MINIAPP_PORT", 8000),
            log_level="info",
            access_log=False
        )
    except Exception as e:
        logger.error(f"❌ Mini-app server error: {e}")

async def register_all_handlers():
    """Register all bot handlers"""
    global gpt_handler, bot
    
    logger.info("📦 Registering handler modules...")
    
    # Handler registration order matters
    handlers_to_register = [
        # Core functionality first
        ("gpt_reply", "register_gpt_reply_handlers"),
        
        # Payment and subscription
        ("subscription_handler", "register_subscription_handlers"),
        ("pay", "register_pay_handlers"),
        
        # Feature handlers
        ("X_handler", "register_X_handlers"),
        ("whale", "register_whale_handlers"),
        ("alerts", "register_alerts_handlers"),
        ("wallet_watch", "register_wallet_handlers"),
        ("ston", "register_ston_handlers"),
    ]
    
    registered_handlers = []
    failed_handlers = []
    
    for module_name, register_function in handlers_to_register:
        try:
            module = importlib.import_module(f'handlers.{module_name}')
            
            if hasattr(module, register_function):
                register_func = getattr(module, register_function)
                
                # Call with appropriate parameters
                import inspect
                sig = inspect.signature(register_func)
                params = list(sig.parameters.keys())
                
                # Pass services as needed
                kwargs = {'dp': dp}
                if 'config' in params:
                    kwargs['config'] = config
                if 'gpt_handler' in params:
                    kwargs['gpt_handler'] = gpt_handler
                # if 'subscription_manager' in params:
                #     kwargs['subscription_manager'] = subscription_manager
                if 'redis_client' in params:
                    kwargs['redis_client'] = redis_client
                if 'bot' in params:
                    kwargs['bot'] = bot
                
                if len(params) == 1:
                    register_func(dp)
                else:
                    register_func(**kwargs)
                
                registered_handlers.append(module_name)
                logger.info(f"✅ Registered handler: {module_name}")
                
            elif hasattr(module, 'router'):
                dp.include_router(module.router)
                registered_handlers.append(module_name)
                logger.info(f"✅ Registered router: {module_name}")
            else:
                logger.warning(f"⚠ No registration method found in {module_name}")
                failed_handlers.append(module_name)
                
        except ImportError:
            logger.warning(f"⚠ Handler {module_name} not found - skipping")
            failed_handlers.append(module_name)
        except Exception as e:
            logger.error(f"❌ Failed to register {module_name}: {e}")
            failed_handlers.append(module_name)
    
    logger.info(f"✅ Successfully registered {len(registered_handlers)} handlers")
    if failed_handlers:
        logger.warning(f"⚠ Failed handlers: {', '.join(failed_handlers)}")
    
    # Register core commands separately with bot instance
    try:
        from bot.commands import register_commands
        
        # Check if register_commands is async
        import inspect
        if inspect.iscoroutinefunction(register_commands):
            await register_commands(dp, config=config, redis_client=redis_client)
        else:
            register_commands(dp, config=config, redis_client=redis_client)
        
        logger.info("✅ Registered core commands")
    except Exception as e:
        logger.error(f"❌ Failed to register core commands: {e}")

async def main():
    """Main application entry point"""
    try:
        logger.info("🎬 TonGPT starting up...")
        
        # Initialize bot
        await initialize_bot()
        
        # Start polling
        await dp.start_polling(
            bot,
            polling_timeout=10,
            handle_signals=True,
            fast=True,
            allowed_updates=["message", "callback_query", "pre_checkout_query"]
        )
        
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user (Ctrl+C)")
    except Exception as e:
        logger.exception(f"🚨 Critical error in main loop: {e}")
        raise
    finally:
        try:
            if bot:
                await bot.session.close()
        except:
            pass

if __name__ == "__main__":
    try:
        # Set process title if possible
        try:
            import setproctitle
            setproctitle.setproctitle("TonGPT-Bot")
        except ImportError:
            pass
        
        asyncio.run(main())
        
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.exception(f"🚨 TonGPT crashed: {e}")
        exit(1)
    finally:
        logger.info("👋 TonGPT process ended")