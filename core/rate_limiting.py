import asyncio
import time
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class RateLimit:
    requests_per_hour: int
    requests_per_minute: int
    burst_limit: int
    
@dataclass 
class RateLimitResult:
    allowed: bool
    remaining: int
    reset_time: int
    retry_after: Optional[int] = None

class AdvancedRateLimiter:
    def __init__(self, redis_client):
        self.redis = redis_client
        
        # Load risk thresholds
        try:
            from core.config import load_config
            cfg = load_config()
            self.free_lifetime_cap = cfg.get("FREE_USER_LIFETIME_AI_QUERIES", 50)
        except Exception:
            self.free_lifetime_cap = 50
        
        # Define rate limits per subscription tier
        self.rate_limits = {
            "free": {
                "api_calls": RateLimit(10, 2, 5),
                "ai_queries": RateLimit(5, 1, 2),
                "scan_requests": RateLimit(3, 1, 1),
                "whale_alerts": RateLimit(0, 0, 0),  # Disabled for free
                "x_monitoring": RateLimit(0, 0, 0)   # Disabled for free
            },
            "basic": {
                "api_calls": RateLimit(100, 10, 20),
                "ai_queries": RateLimit(50, 5, 10),
                "scan_requests": RateLimit(20, 3, 5),
                "whale_alerts": RateLimit(10, 2, 3),
                "x_monitoring": RateLimit(5, 1, 2)
            },
            "premium": {
                "api_calls": RateLimit(1000, 100, 200),
                "ai_queries": RateLimit(500, 50, 100),
                "scan_requests": RateLimit(100, 10, 20),
                "whale_alerts": RateLimit(100, 10, 20),
                "x_monitoring": RateLimit(50, 5, 10)
            }
        }
    
    async def check_rate_limit(self, user_id: int, tier: str, endpoint: str, ip_address: str = None) -> RateLimitResult:
        """
        Check rate limit using sliding window algorithm with burst protection
        """
        try:
            # Get rate limit configuration
            limits = self.rate_limits.get(tier, self.rate_limits["free"])
            endpoint_limit = limits.get(endpoint)
            
            if not endpoint_limit:
                return RateLimitResult(allowed=True, remaining=999, reset_time=0)
            
            # If endpoint is disabled for this tier
            if endpoint_limit.requests_per_hour == 0:
                return RateLimitResult(
                    allowed=False, 
                    remaining=0, 
                    reset_time=0,
                    retry_after=None  # Upgrade required
                )
            
            current_time = int(time.time())
            
            # Lifetime checking for free tier AI queries
            if endpoint == "ai_queries" and tier == "free":
                lifetime_key = f"lifetime_ai_queries:{user_id}"
                lifetime_count = int(self.redis.get(lifetime_key) or 0)
                if lifetime_count >= self.free_lifetime_cap:
                    return RateLimitResult(
                        allowed=False, 
                        remaining=0, 
                        reset_time=current_time + 86400,
                        retry_after=None  # Upgrade required
                    )
            
            # Check multiple windows: minute, hour, and burst
            checks = [
                ("minute", endpoint_limit.requests_per_minute, 60),
                ("hour", endpoint_limit.requests_per_hour, 3600),
                ("burst", endpoint_limit.burst_limit, 10)  # 10 second burst window
            ]
            
            for window_type, limit, window_seconds in checks:
                result = await self._check_window(user_id, endpoint, window_type, limit, window_seconds, current_time)
                if not result.allowed:
                    return result
            
            # Also check IP-based rate limiting for abuse prevention
            if ip_address:
                ip_result = await self._check_ip_rate_limit(ip_address, endpoint, current_time)
                if not ip_result.allowed:
                    return ip_result
            
            # All checks passed - increment counters
            await self._increment_counters(user_id, endpoint, current_time)
            
            # Calculate remaining requests (use most restrictive)
            remaining = await self._calculate_remaining(user_id, tier, endpoint, current_time)
            
            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                reset_time=current_time + 3600  # Next hour reset
            )
            
        except Exception as e:
            logger.error(f"Rate limiting error: {e}")
            # Fail closed - deny request if rate limiter fails
            return RateLimitResult(allowed=False, remaining=0, reset_time=int(time.time()) + 60, retry_after=60)
    
    async def _check_window(self, user_id: int, endpoint: str, window_type: str, limit: int, window_seconds: int, current_time: int) -> RateLimitResult:
        """Check rate limit for specific time window"""
        if limit == 0:
            return RateLimitResult(allowed=True, remaining=limit, reset_time=current_time)
        
        key = f"rate_limit:{user_id}:{endpoint}:{window_type}"
        window_start = current_time - window_seconds
        
        # Use Redis sorted set for sliding window
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)  # Remove old entries
        pipe.zcard(key)  # Count current requests
        pipe.expire(key, window_seconds)
        
        # Redis pipeline execution is synchronous; run it off the event loop.
        results = await asyncio.to_thread(pipe.execute)
        current_requests = results[1]
        
        if current_requests >= limit:
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_time=current_time + window_seconds,
                retry_after=window_seconds
            )
        
        return RateLimitResult(
            allowed=True,
            remaining=limit - current_requests,
            reset_time=current_time + window_seconds
        )
    
    async def _check_ip_rate_limit(self, ip_address: str, endpoint: str, current_time: int) -> RateLimitResult:
        """IP-based rate limiting to prevent abuse"""
        # More aggressive limits for IP-based checking
        ip_limits = {
            "ai_queries": 20,  # Max 20 AI queries per hour per IP
            "scan_requests": 30,  # Max 30 scans per hour per IP
            "api_calls": 200   # Max 200 API calls per hour per IP
        }
        
        # Burst tracking for IP
        burst_key = f"ip_burst:{ip_address}:10m"
        pipe = self.redis.pipeline()
        pipe.incr(burst_key)
        pipe.expire(burst_key, 600)  # 10 minutes
        burst_count = pipe.execute()[0]
        
        if burst_count > 60:  # >60 requests in 10 mins from same IP
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_time=current_time + 600,
                retry_after=600
            )
        
        limit = ip_limits.get(endpoint, 100)  # Default limit
        key = f"ip_rate_limit:{ip_address}:{endpoint}:hour"
        window_start = current_time - 3600  # 1 hour window
        
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        pipe.expire(key, 3600)
        
        results = pipe.execute()
        current_requests = results[1]
        
        if current_requests >= limit:
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_time=current_time + 3600,
                retry_after=3600
            )
        
        return RateLimitResult(allowed=True, remaining=limit - current_requests, reset_time=current_time + 3600)
    
    async def _increment_counters(self, user_id: int, endpoint: str, current_time: int):
        """Increment rate limit counters"""
        windows = [
            ("minute", 60),
            ("hour", 3600), 
            ("burst", 10)
        ]
        
        pipe = self.redis.pipeline()
        
        for window_type, window_seconds in windows:
            key = f"rate_limit:{user_id}:{endpoint}:{window_type}"
            pipe.zadd(key, {str(current_time): current_time})
            pipe.expire(key, window_seconds)
            
        if endpoint == "ai_queries":
            lifetime_key = f"lifetime_ai_queries:{user_id}"
            pipe.incr(lifetime_key)
        
        pipe.execute()
    
    async def _calculate_remaining(self, user_id: int, tier: str, endpoint: str, current_time: int) -> int:
        """Calculate remaining requests for the most restrictive window"""
        limits = self.rate_limits.get(tier, self.rate_limits["free"])
        endpoint_limit = limits.get(endpoint)
        
        if not endpoint_limit:
            return 999
        
        # Check minute window (most restrictive for immediate usage)
        key = f"rate_limit:{user_id}:{endpoint}:minute"
        current_requests = self.redis.zcard(key)
        
        return max(0, endpoint_limit.requests_per_minute - current_requests)
    
    async def get_rate_limit_status(self, user_id: int, tier: str) -> Dict[str, Any]:
        """Get comprehensive rate limit status for user"""
        current_time = int(time.time())
        status = {}
        
        limits = self.rate_limits.get(tier, self.rate_limits["free"])
        
        for endpoint, limit_config in limits.items():
            endpoint_status = {}
            
            for window_type, window_seconds in [("minute", 60), ("hour", 3600)]:
                key = f"rate_limit:{user_id}:{endpoint}:{window_type}"
                current_requests = self.redis.zcard(key)
                
                if window_type == "minute":
                    max_requests = limit_config.requests_per_minute
                else:
                    max_requests = limit_config.requests_per_hour
                
                endpoint_status[window_type] = {
                    "used": current_requests,
                    "limit": max_requests,
                    "remaining": max(0, max_requests - current_requests),
                    "reset_time": current_time + window_seconds
                }
            
            status[endpoint] = endpoint_status
        
        return status
    
    async def reset_user_rate_limits(self, user_id: int):
        """Reset all rate limits for a user (admin function)"""
        pattern = f"rate_limit:{user_id}:*"
        keys = self.redis.keys(pattern)
        if keys:
            self.redis.delete(*keys)
    
    async def add_rate_limit_exemption(self, user_id: int, endpoint: str, duration_seconds: int = 3600):
        """Temporarily exempt user from rate limits"""
        key = f"rate_limit_exempt:{user_id}:{endpoint}"
        self.redis.setex(key, duration_seconds, "1")
    
    async def is_rate_limit_exempt(self, user_id: int, endpoint: str) -> bool:
        """Check if user is exempt from rate limits"""
        key = f"rate_limit_exempt:{user_id}:{endpoint}"
        return bool(self.redis.get(key))

    async def get_user_risk_score(self, user_id: int, tier: str = "free", ip_address: str = None) -> Tuple[int, str]:
        """Calculate unified risk score and return (score, tier_name)"""
        try:
            # 1. Identity Risk
            identity_risk = 0
            history_key = f"user_history:{user_id}"
            has_history = self.redis.exists(history_key)
            if not has_history:
                identity_risk += 20
                
            # 2. Behavior Risk
            behavior_risk = 0
            ai_key = f"rate_limit:{user_id}:ai_queries:hour"
            other_key = f"rate_limit:{user_id}:api_calls:hour"
            
            ai_count = self.redis.zcard(ai_key)
            other_count = self.redis.zcard(other_key)
            
            if ai_count > 10 and other_count == 0:
                behavior_risk += 35
                
            minute_ai_key = f"rate_limit:{user_id}:ai_queries:minute"
            if self.redis.zcard(minute_ai_key) > 3:
                behavior_risk += 20
                
            # 3. IP Risk
            ip_risk = 0
            if ip_address:
                ip_hour_key = f"ip_rate_limit:{ip_address}:ai_queries:hour"
                if self.redis.zcard(ip_hour_key) > 20:
                    ip_risk += 40
                burst_key = f"ip_burst:{ip_address}:10m"
                if int(self.redis.get(burst_key) or 0) > 40:
                    ip_risk += 30
                    
            # 4. Economic Risk
            economic_risk = 0
            if tier == "free":
                lifetime_key = f"lifetime_ai_queries:{user_id}"
                lifetime_count = int(self.redis.get(lifetime_key) or 0)
                if lifetime_count > self.free_lifetime_cap * 0.8:
                    economic_risk += 30
            
            total_risk = min(100, int(identity_risk * 0.25 + behavior_risk * 0.45 + ip_risk * 0.20 + economic_risk * 0.10))
            
            if total_risk < 30:
                tier_name = "Trusted"
            elif total_risk < 60:
                tier_name = "Watch"
            elif total_risk < 80:
                tier_name = "Suspicious"
            else:
                tier_name = "High Risk"
                
            return total_risk, tier_name
        except Exception as e:
            logger.error(f"Error calculating risk score: {e}")
            return 0, "Trusted"

class RateLimitMiddleware:
    """Middleware for automatic rate limiting in handlers"""
    
    def __init__(self, rate_limiter: AdvancedRateLimiter, subscription_manager=None):
        self.rate_limiter = rate_limiter
        self.subscription_manager = subscription_manager
    
    async def check_and_consume(self, user_id: int, endpoint: str, message=None) -> Tuple[bool, str]:
        """
        Check rate limit and return (allowed, error_message)
        """
        try:
            # Get user tier (from subscription_manager or engine)
            tier = "free"
            if self.subscription_manager:
                subscription = await self.subscription_manager.get_user_subscription(user_id)
                if subscription:
                    tier = subscription.tier
            else:
                try:
                    from services.engine_client import engine_client
                    status = await engine_client.get_user_status(str(user_id))
                    tier = (status.get("plan") or "Free").lower()
                except Exception:
                    pass
            
            # IP only when available (webhook/miniapp). Bot messages have no HTTP IP.
            ip_address = getattr(message, "_ip_address", None) if message else None
            
            # Check terms acceptance (version-aware)
            CURRENT_TOS_VERSION = "1.0"
            if getattr(self.rate_limiter.redis, "client", self.rate_limiter.redis):
                redis_instance = getattr(self.rate_limiter.redis, "client", self.rate_limiter.redis)
                accepted_version = redis_instance.get(f"terms_accepted:{user_id}")
                if isinstance(accepted_version, bytes):
                    accepted_version = accepted_version.decode()
                if accepted_version != CURRENT_TOS_VERSION and endpoint not in ["terms", "start", "accept_terms"]:
                    return False, "⚠️ <b>Action Required</b>\n\nYou must accept our Terms of Service and Privacy Policy before using TonGPT.\n\nPlease use /accept_terms to continue."
            
            # Check if exempt
            if await self.rate_limiter.is_rate_limit_exempt(user_id, endpoint):
                return True, ""
            
            # Check rate limit
            result = await self.rate_limiter.check_rate_limit(user_id, tier, endpoint, ip_address)
            
            if not result.allowed:
                if result.retry_after is None:
                    # Upgrade required
                    error_msg = (
                        f"🚫 <b>Feature Not Available</b>\n\n"
                        f"The {endpoint} feature is not available on your current plan.\n"
                        f"Use /upgrade to access this feature!"
                    )
                else:
                    # Rate limited
                    minutes_left = result.retry_after // 60
                    error_msg = (
                        f"⏰ <b>Rate Limit Exceeded</b>\n\n"
                        f"You've reached your {endpoint} limit for {tier} plan.\n"
                        f"Try again in {minutes_left} minutes or /upgrade for higher limits!"
                    )
                
                return False, error_msg
            
            return True, ""
            
        except Exception as e:
            logger.error(f"Rate limit middleware error: {e}")
            # Fail closed
            return False, "⚠️ Service temporarily unavailable due to internal error."

# Global rate limiter instance
_rate_limiter = None

def get_rate_limiter(redis_client=None):
    """Get or create rate limiter instance"""
    global _rate_limiter
    if _rate_limiter is None and redis_client:
        _rate_limiter = AdvancedRateLimiter(redis_client)
    return _rate_limiter

def create_rate_limit_decorator(endpoint: str):
    """Create decorator for automatic rate limiting"""
    def decorator(func):
        async def wrapper(message, *args, **kwargs):
            # Get rate limiter
            rate_limiter = get_rate_limiter()
            if not rate_limiter or not getattr(rate_limiter.redis, "client", None):
                return await func(message, *args, **kwargs)
            
            # Create middleware
            middleware = RateLimitMiddleware(rate_limiter)
            user_id = message.from_user.id
            
            # --- Global Concurrency Cap ---
            rc = getattr(rate_limiter.redis, "client", rate_limiter.redis)
            concurrency_key = f"active_req:{user_id}:{endpoint}"
            try:
                current_active = rc.incr(concurrency_key)
                if current_active == 1:
                    rc.expire(concurrency_key, 300) # Fail-safe TTL to clear stuck connections
                    
                if current_active > 2: # Max 2 concurrent GPT processing per user
                    rc.decr(concurrency_key)
                    await message.reply("⏳ Please wait for your previous request to finish processing.", parse_mode="HTML")
                    return
            except Exception as e:
                logger.debug(f"Concurrency track error: {e}")
            # ------------------------------
            
            try:
                # Check rate limit
                allowed, error_msg = await middleware.check_and_consume(
                    user_id, 
                    endpoint, 
                    message
                )
                
                if not allowed:
                    await message.reply(error_msg, parse_mode="HTML")
                    return
                
                # Proceed with original function
                return await func(message, *args, **kwargs)
            finally:
                try:
                    rc.decr(concurrency_key)
                except Exception:
                    pass
        
        return wrapper
    return decorator