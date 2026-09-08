import asyncio
import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

async def initialize_gpt_handler(config: Dict[str, Any]) -> Optional[Any]:
    """Initialize the enhanced GPT handler"""
    try:
        from handlers.enhanced_gpt_handler import EnhancedGPTHandler
        
        # Determine which API to use
        api_key = config["OPENROUTER_API_KEY"] or config["OPENAI_API_KEY"]
        model = "gpt-4" if config["OPENAI_API_KEY"] and not config["OPENROUTER_API_KEY"] else "openai/gpt-4"
        
        gpt_handler = EnhancedGPTHandler(api_key, model)
        logger.info("✅ Enhanced GPT handler initialized")
        return gpt_handler
        
    except ImportError:
        logger.warning("⚠ Enhanced GPT handler not found. Basic responses only.")
        return None
    except Exception as e:
        logger.error(f"❌ Failed to initialize GPT handler: {e}")
        return None

# X/Twitter monitoring removed (2026-07 launch cleanup).
# Subscription manager removed - handled by C# Engine directly

async def test_connections(config: Dict[str, Any]) -> None:
    """Test all external service connections"""
    logger.info("🔍 Testing external service connections...")
    
    # Test Redis connection.
    # INIT-003 / LAUNCH-FIX 5: SafeRedisClient.ping() returns False instead of
    # raising, so the old code logged "successful" even when Redis was down —
    # while other subsystems (analysis_cache) correctly reported it missing.
    # Check the RETURN VALUE.
    try:
        from utils.redis_conn import redis_client
        if redis_client.ping():
            logger.info("✅ Redis connection successful")
        else:
            logger.error("❌ Redis ping returned false — Redis is NOT available "
                         "(caches and rate limits will degrade)")
    except ImportError:
        logger.warning("⚠ Redis module not found. Some features may be limited.")
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")

    # Test GPT connection. LAUNCH-FIX 3: health_check surfaces the real
    # HTTP status / error body; test_gpt_connection logs it.
    try:
        if config["OPENROUTER_API_KEY"] or config["OPENAI_API_KEY"]:
            from gpt.engine import test_gpt_connection
            if await test_gpt_connection():
                logger.info("✅ GPT connection test passed")
            else:
                logger.error("❌ GPT connection test failed — see 'GPT health "
                             "check FAILED' line above for the exact cause")
        else:
            logger.error("❌ No GPT API key configured")
    except ImportError:
        logger.warning("⚠ GPT engine module not found. AI features will be disabled.")
    except Exception as e:
        logger.error(f"❌ GPT test error: {e}")
    
    # Test TON API connection
    try:
        from services.tonapi import test_ton_api_connection
        api_status = await test_ton_api_connection()  # now async
        if api_status.get('api_status') == 'online':
            logger.info("✅ TON API connection successful")
        else:
            logger.warning(f"⚠ TON API connection issues: {api_status}")
    except ImportError:
        logger.warning("⚠ TON API service not found. Blockchain features will be limited.")
    except Exception as e:
        logger.error(f"❌ TON API test error: {e}")

# INIT-001: guard so a RETRIED initialize_all_services() (the on_startup retry
# loop) can never spawn a second copy of these background tasks.
_bg_tasks_started = False


async def start_background_tasks(services: Dict[str, Any]) -> None:
    """Start all background monitoring tasks (idempotent)."""
    global _bg_tasks_started
    if _bg_tasks_started:
        logger.info("Background tasks already started — skipping duplicate start (INIT-001).")
        return
    _bg_tasks_started = True

    # Start wallet monitoring (blockchain.py) when Redis is available
    try:
        from utils.redis_conn import redis_client
        if redis_client:
            from services.monitor import monitor_followed_wallets
            asyncio.create_task(monitor_followed_wallets())
            logger.info("👛 Wallet monitoring (followed addresses) started.")
    except Exception as e:
        logger.warning("⚠ Wallet monitoring not started: %s", e)

    # Start periodic notification cleanup
    try:
        from services.notifications import notification_cleanup_loop
        retention_days = int(os.getenv("NOTIFICATION_RETENTION_DAYS", "30"))
        asyncio.create_task(notification_cleanup_loop(retention_days=retention_days))
        logger.info("🧹 Notification cleanup loop started")
    except Exception as e:
        logger.warning("⚠ Notification cleanup not started: %s", e)  # INIT-002: correct message

async def initialize_all_services(config: Dict[str, Any]) -> Dict[str, Any]:
    """Initialize all services and return service instances"""
    services = {}
    
    # Initialize GPT handler
    services['gpt_handler'] = await initialize_gpt_handler(config)

    # Subscription manager removed
    # services['subscription_manager'] = await initialize_subscription_manager(config)
    
    # Test connections
    await test_connections(config)
    
    # Start background tasks
    await start_background_tasks(services)
    
    return services