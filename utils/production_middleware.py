
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message
from typing import Callable, Dict, Any, Awaitable
import logging
import time

logger = logging.getLogger(__name__)

class RateLimitMiddleware(BaseMiddleware):
    """Rate limiting middleware for production"""
    
    def __init__(self, rate_limiter):
        self.rate_limiter = rate_limiter
        super().__init__()
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        
        # Only apply to messages
        if not isinstance(event, Message):
            return await handler(event, data)

        # Money has already moved: reach activation/queueing regardless of quota.
        # Bypass the tier lookup too so it cannot delay payment processing.
        if event.successful_payment is not None:
            return await handler(event, data)
        
        user_id = event.from_user.id
        
        # Get user tier from C# Engine
        try:
            from services.engine_client import engine_client
            status = await engine_client.get_user_status(str(user_id))
            tier = status.get('tier', 'free').lower()
        except Exception as e:
            logger.warning(f"Failed to fetch user tier: {e}")
            tier = "free"
        
        # Check rate limit
        is_limited, rate_info = await self.rate_limiter.check_rate_limit(user_id, tier)
        
        if is_limited:
            # Derive "current" defensively: check_rate_limit returns limit/remaining
            # (not "current"), so compute it and fall back safely to avoid KeyErrors.
            limit = rate_info.get("limit", 0)
            remaining = rate_info.get("remaining", 0)
            current = rate_info.get("current", max(limit - remaining, 0))
            reset_time = rate_info.get("reset_time", int(time.time()))
            await event.reply(
                f"🚫 <b>Rate limit exceeded!</b>\n\n"
                f"⏰ You've made {current}/{limit} requests this hour.\n"
                f"🔄 Reset time: <code>{time.strftime('%H:%M', time.localtime(reset_time))}</code>\n\n"
                f"💎 Upgrade to Basic or Premium for higher limits:\n"
                f"/upgrade",
                parse_mode="HTML"
            )
            return
        
        # Add rate info to data for handlers to use
        data["rate_info"] = rate_info
        
        return await handler(event, data)

class LoggingMiddleware(BaseMiddleware):
    """Production logging middleware"""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        
        if isinstance(event, Message):
            user_id = event.from_user.id
            username = event.from_user.username or "unknown"
            command = event.text.split()[0] if event.text else "no_text"
            
            logger.info(f"User {user_id} (@{username}) executed: {command}")
        
        start_time = time.time()
        result = await handler(event, data)
        duration = time.time() - start_time
        
        if duration > 2.0:  # Log slow handlers
            logger.warning(f"Slow handler: {duration:.2f}s for {type(event).__name__}")
        
        return result
