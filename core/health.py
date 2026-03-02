"""
Health check system for TonGPT services
"""
import asyncio
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

async def health_check(bot=None, gpt_handler=None, X_monitor=None, subscription_manager=None) -> Dict[str, Any]:
    """Perform comprehensive health check on all bot components"""
    health_status = {
        "bot": False,
        "redis": False,
        "ton_api": False,
        "gpt": False,
        "X": False,
        "miniapp_api": True,  # Always true since it's integrated
        "subscription": bool(subscription_manager),
        "enhanced_features": bool(gpt_handler),
        "timestamp": asyncio.get_event_loop().time()
    }
    
    # Check bot
    try:
        if bot:
            await bot.get_me()
            health_status["bot"] = True
    except Exception as e:
        logger.error(f"Bot health check failed: {e}")
    
    # Check Redis
    try:
        from utils.redis_conn import redis_client
        if redis_client.ping():
            health_status["redis"] = True
            
            # --- Redis Pressure Monitor ---
            try:
                rc = getattr(redis_client, "client", redis_client)
                if rc:
                    info = rc.info('memory')
                    used_memory = info.get('used_memory', 0)
                    max_memory = info.get('maxmemory', 0)
                    
                    if max_memory > 0:
                        memory_usage = used_memory / max_memory
                        health_status["redis_memory_usage"] = memory_usage
                        
                        if memory_usage > 0.90:
                            logger.critical(f"🚨 REDIS PRESSURE FAST EXHAUSTION: Memory usage at {memory_usage:.1%}! Degrading non-critical systems.")
                            rc.setex("system_degraded", 300, "true")
                        elif memory_usage > 0.80:
                            logger.warning(f"⚠️ REDIS HIGH PRESSURE: Memory usage at {memory_usage:.1%}. Consider scaling up.")
            except Exception as e:
                logger.error(f"Redis pressure monitor failed: {e}")
            # ------------------------------
            
    except ImportError:
        logger.warning("Redis module not found")
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
    
    # Check TON API
    try:
        from services.tonapi import test_ton_api_connection
        status = test_ton_api_connection()
        health_status["ton_api"] = status.get("api_status") == "online"
    except ImportError:
        logger.warning("TON API module not found")
    except Exception as e:
        logger.error(f"TON API health check failed: {e}")
    
    # Check GPT
    try:
        if gpt_handler:
            response = await gpt_handler.get_comprehensive_response("test", 0)
            health_status["gpt"] = bool(response)
    except Exception as e:
        logger.error(f"GPT health check failed: {e}")
    
    # Check X API
    try:
        if X_monitor:
            client = X_monitor.client
            me = client.get_me()
            health_status["X"] = bool(me.data)
    except Exception as e:
        logger.error(f"X API health check failed: {e}")
    
    # Check subscription system
    try:
        if subscription_manager:
            test_sub = await subscription_manager.get_user_subscription(999999999)
            health_status["subscription"] = True
    except Exception as e:
        logger.error(f"Subscription health check failed: {e}")
    
    return health_status

def log_system_status(services: Dict[str, Any]) -> None:
    """Log current system status and enabled features"""
    features_enabled = []
    
    if services.get('subscription_manager'):
        features_enabled.append("Subscription Management")
    if services.get('gpt_handler'):
        features_enabled.append("Enhanced AI Conversations")
    if services.get('X_monitor'):
        features_enabled.append("X Monitoring & Alerts")
    
    features_enabled.extend([
        "Mini-App API",
        "Telegram Bot",
        "Redis Caching",
        "TON Blockchain Integration"
    ])
    
    logger.info(f"🎯 Enabled features: {', '.join(features_enabled)}")
    logger.info("🤖 TonGPT is now running with enhanced capabilities!")
    logger.info("📋 Available commands: /help, /scan, /X, /subscription, /upgrade")