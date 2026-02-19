import asyncio
import logging
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

async def initialize_X_monitor(config: Dict[str, Any]) -> Optional[Any]:
    """Initialize X monitoring service"""
    if not all([config["X_API_KEY"], config["X_API_SECRET"], config["X_BEARER_TOKEN"]]):
        logger.warning("⚠ X API credentials incomplete - monitoring disabled")
        return None
    
    try:
        from services.X_monitor import XMonitor
        X_monitor = XMonitor()
        logger.info("✅ X monitor initialized")
        return X_monitor
        
    except ImportError:
        logger.warning("⚠ X monitor module not found")
        return None
    except Exception as e:
        logger.error(f"❌ Failed to initialize X monitor: {e}")
        return None

# Subscription manager removed - handled by C# Engine directly

async def test_connections(config: Dict[str, Any]) -> None:
    """Test all external service connections"""
    logger.info("🔍 Testing external service connections...")
    
    # Test Redis connection
    try:
        from utils.redis_conn import redis_client
        redis_client.ping()
        logger.info("✅ Redis connection successful")
    except ImportError:
        logger.warning("⚠ Redis module not found. Some features may be limited.")
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
    
    # Test GPT connection
    try:
        if config["OPENROUTER_API_KEY"]:
            from gpt.engine import test_gpt_connection
            if await test_gpt_connection():
                logger.info("✅ OpenRouter GPT connection test passed")
            else:
                logger.error("❌ OpenRouter GPT connection test failed")
        elif config["OPENAI_API_KEY"]:
            logger.info("✅ Using OpenAI API as GPT provider")
        else:
            logger.error("❌ No GPT API key configured")
    except ImportError:
        logger.warning("⚠ GPT engine module not found. AI features will be disabled.")
    except Exception as e:
        logger.error(f"❌ GPT test error: {e}")
    
    # Test TON API connection
    try:
        from services.tonapi import test_ton_api_connection
        api_status = test_ton_api_connection()
        if api_status.get('api_status') == 'online':
            logger.info("✅ TON API connection successful")
        else:
            logger.warning(f"⚠ TON API connection issues: {api_status}")
    except ImportError:
        logger.warning("⚠ TON API service not found. Blockchain features will be limited.")
    except Exception as e:
        logger.error(f"❌ TON API test error: {e}")

async def start_background_tasks(services: Dict[str, Any]) -> None:
    """Start all background monitoring tasks"""
    X_monitor = services.get('X_monitor')
    # subscription_manager = services.get('subscription_manager')
    
    # Start X monitoring
    if X_monitor:
        logger.info("🐦 Starting X monitoring service...")
        asyncio.create_task(X_monitor.enhanced_monitoring_cycle())
    
    # Subscription cleanup removed

    # Subscription cleanup removed - handled by C# Engine or TTL

async def initialize_all_services(config: Dict[str, Any]) -> Dict[str, Any]:
    """Initialize all services and return service instances"""
    services = {}
    
    # Initialize GPT handler
    services['gpt_handler'] = await initialize_gpt_handler(config)
    
    # Initialize X monitor
    services['X_monitor'] = await initialize_X_monitor(config)
    
    # Subscription manager removed
    # services['subscription_manager'] = await initialize_subscription_manager(config)
    
    # Test connections
    await test_connections(config)
    
    # Start background tasks
    await start_background_tasks(services)
    
    return services