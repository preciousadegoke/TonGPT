import time
import asyncio
from typing import Dict, Tuple, Any, Optional
import logging

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, redis_client: Optional[object] = None):
        """Initialize rate limiter with optional Redis client"""
        if redis_client is None:
            logger.warning("RateLimiter initialized without Redis - using in-memory fallback")
            self._memory_cache: Dict[str, Dict[int, int]] = {}
            self._use_memory = True
        else:
            self._use_memory = False
        self.redis_client = redis_client
        self.default_limits = {
            "free": {"requests_per_hour": 10, "burst": 3},
            "basic": {"requests_per_hour": 100, "burst": 20},
            "premium": {"requests_per_hour": 1000, "burst": 50}
        }
    
    async def check_rate_limit(self, user_id: int, tier: str = "free") -> Tuple[bool, Dict[str, Any]]:
        """Check if user is rate limited"""
        now = time.time()
        window_start = int(now // 3600) * 3600  # Hour window
        
        limits = self.default_limits.get(tier, self.default_limits["free"])
        key = f"rate_limit:{user_id}:{window_start}"
        
        try:
            if self._use_memory:
                return self._check_rate_limit_memory(user_id, window_start, limits, key)
            else:
                return await self._check_rate_limit_redis(user_id, window_start, limits, key)
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}", exc_info=True)
            # Allow request on error
            return False, {"error": "Rate limiter unavailable"}
    
    def _check_rate_limit_memory(self, user_id: int, window_start: int, limits: Dict, key: str) -> Tuple[bool, Dict[str, Any]]:
        """Check rate limit using in-memory cache"""
        limit = limits["requests_per_hour"]
        
        if window_start not in self._memory_cache:
            self._memory_cache[window_start] = {}
        
        current_requests = self._memory_cache[window_start].get(user_id, 0)
        
        if current_requests >= limit:
            return True, {
                "error": "Rate limit exceeded",
                "limit": limit,
                "current": current_requests,
                "reset_time": window_start + 3600,
                "tier": limits.get("tier", "free")
            }
        
        # Increment counter
        self._memory_cache[window_start][user_id] = current_requests + 1
        
        return False, {
            "requests_made": current_requests + 1,
            "limit": limit,
            "remaining": limit - current_requests - 1,
            "reset_time": window_start + 3600,
            "tier": limits.get("tier", "free")
        }
    
    async def _check_rate_limit_redis(self, user_id: int, window_start: int, limits: Dict, key: str) -> Tuple[bool, Dict[str, Any]]:
        """Check rate limit using Redis"""
        limit = limits["requests_per_hour"]
        
        # Get current value (returns None if doesn't exist)
        current_requests = self.redis_client.get(key)
        current_requests = int(current_requests) if current_requests else 0
        
        if current_requests >= limit:
            return True, {
                "error": "Rate limit exceeded",
                "limit": limit,
                "current": current_requests,
                "reset_time": window_start + 3600,
                "tier": limits.get("tier", "free")
            }
        
        # Increment counter
        self.redis_client.incr(key)
        self.redis_client.expire(key, 3600)
        
        return False, {
            "requests_made": current_requests + 1,
            "limit": limit,
            "remaining": limit - current_requests - 1,
            "reset_time": window_start + 3600,
            "tier": limits.get("tier", "free")
        }
