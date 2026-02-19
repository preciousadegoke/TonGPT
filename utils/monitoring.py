import asyncio
import logging
from datetime import datetime
import time

logger = logging.getLogger(__name__)

class ProductionMonitor:
    def __init__(self, redis_client, bot):
        self.redis_client = redis_client
        self.bot = bot
        
    async def log_user_activity(self, user_id: int, action: str):
        """Log user activity"""
        timestamp = int(time.time())
        await self.redis_client.zadd(f"user_activity:{user_id}", {action: timestamp})
        
        # Keep only last 100 activities
        await self.redis_client.zremrangebyrank(f"user_activity:{user_id}", 0, -101)
    
    async def get_system_stats(self):
        """Get system statistics"""
        stats = {
            "active_users_24h": 0,
            "total_commands_24h": 0,
            "subscription_breakdown": {"free": 0, "basic": 0, "premium": 0},
            "revenue_24h": 0.0,
            "uptime": 0
        }
        
        try:
            # Get active users
            yesterday = int(time.time()) - 86400
            keys = await self.redis_client.keys("user_activity:*")
            
            for key in keys:
                recent_activity = await self.redis_client.zrangebyscore(key, yesterday, "+inf")
                if recent_activity:
                    stats["active_users_24h"] += 1
                    stats["total_commands_24h"] += len(recent_activity)
            
            # Get subscription breakdown
            subscription_keys = await self.redis_client.keys("subscription:*")
            for key in subscription_keys:
                subscription_data = await self.redis_client.hgetall(key)
                tier = subscription_data.get("tier", "free")
                stats["subscription_breakdown"][tier] += 1
            
            # Calculate revenue (basic * 5 + premium * 15)
            stats["revenue_24h"] = (
                stats["subscription_breakdown"]["basic"] * 5.0 +
                stats["subscription_breakdown"]["premium"] * 15.0
            )
            
            # Get uptime
            startup_time = await self.redis_client.get("bot_startup_time")
            if startup_time:
                stats["uptime"] = int(time.time()) - int(startup_time)
            
        except Exception as e:
            logger.error(f"Error getting system stats: {e}")
        
        return stats
    
    async def health_check(self):
        """Comprehensive health check"""
        health = {"status": "healthy", "services": {}}
        
        # Check Redis
        try:
            await self.redis_client.ping()
            health["services"]["redis"] = "online"
        except:
            health["services"]["redis"] = "offline"
            health["status"] = "degraded"
        
        # Check bot
        try:
            await self.bot.get_me()
            health["services"]["bot"] = "online"
        except:
            health["services"]["bot"] = "offline" 
            health["status"] = "critical"
        
        return health