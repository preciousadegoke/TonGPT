import aiohttp
import logging
import os
import json
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)

class EngineClient:
    """
    Client for interactions with the C# TonGPT.Engine API.
    Acts as the single source of truth for data persistence, replacing local databases.
    """
    
    def __init__(self, base_url: str = None):
        if base_url:
            self.base_url = base_url.rstrip('/')
        else:
        else:
            self.base_url = os.getenv("ENGINE_URL", "http://localhost:5090/api").rstrip('/')
        self.api_key = os.getenv("ENGINE_API_KEY", "tongpt-secret-key-123")
        self.headers = {"X-API-Key": self.api_key, "Content-Type": "application/json"}
        
    async def _get(self, endpoint: str) -> Dict[str, Any]:
        """Internal helper for GET requests"""
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                async with session.get(f"{self.base_url}/{endpoint}") as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 404:
                         return None
                    
                    logger.warning(f"Engine API GET {endpoint} failed: {response.status}")
                    return {}
            except Exception as e:
                logger.error(f"Engine API connection failed: {e}")
                return {}

    async def _post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Internal helper for POST requests"""
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                async with session.post(f"{self.base_url}/{endpoint}", json=data) as response:
                    if response.status in [200, 201]:
                        return await response.json()
                    
                    error_text = await response.text()
                    logger.warning(f"Engine API POST {endpoint} failed: {response.status} - {error_text}")
                    return {"error": response.status, "message": error_text}
            except Exception as e:
                logger.error(f"Engine API connection failed: {e}")
                return {"error": "connection_failed"}

    # ==========================================
    # User Management
    # ==========================================

    async def create_or_update_user(self, telegram_id: int, username: str = None, 
                                   first_name: str = None, last_name: str = None) -> bool:
        """Create or update user in the backend"""
        data = {
            "telegramId": telegram_id,
            "username": username,
            "firstName": first_name,
            "lastName": last_name
        }
        # Assuming Endpoint: POST /api/User/sync
        result = await self._post("User/sync", data)
        return "error" not in result

    async def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get user details by Telegram ID"""
        return await self._get(f"User/{telegram_id}")

    # ==========================================
    # Chat & Context
    # ==========================================

    async def save_chat_message(self, telegram_id: int, user_message: str, ai_response: str) -> bool:
        """Save a chat interaction"""
        data = {
            "telegramId": telegram_id,
            "userMessage": user_message,
            "aiResponse": ai_response,
            "timestamp": datetime.utcnow().isoformat()
        }
        result = await self._post("Chat/message", data)
        return "error" not in result

    async def get_chat_context(self, telegram_id: int, limit: int = 10) -> List[Dict[str, str]]:
        """
        Get recent chat history formatted for AI context.
        Returns: List of {"role": "user/assistant", "content": "..."}
        """
        # Assuming GET /api/Chat/history/{id}?limit=10 returns list of raw messages
        result = await self._get(f"Chat/history/{telegram_id}?limit={limit}")
        
        # If API is not ready or returns empty, return empty list
        if not result or not isinstance(result, list):
            return []

        # Convert to OpenAI format
        context = []
        # sort by time ascending if needed
        for msg in result:
            if "userMessage" in msg:
                 context.append({"role": "user", "content": msg["userMessage"]})
            if "aiResponse" in msg:
                 context.append({"role": "assistant", "content": msg["aiResponse"]})
        
        return context

    # ==========================================
    # Subscription & Payments
    # ==========================================

    async def get_user_status(self, telegram_id: str) -> Dict[str, Any]:
        """Check user subscription status"""
        return await self._get(f"Subscription/status/{telegram_id}") or {"tier": "free", "credits": 0}

    async def upgrade_user(self, telegram_id: str, plan: str) -> bool:
        """Upgrade user plan"""
        result = await self._post("Subscription/upgrade", {
            "telegramId": str(telegram_id),
            "plan": plan
        })
        return result.get("status") == "Success"

    # ==========================================
    # Analytics & Logging
    # ==========================================

    async def log_activity(self, telegram_id: int, action: str, metadata: Dict = None) -> bool:
        """Log user action for analytics"""
        data = {
            "telegramId": telegram_id,
            "action": action,
            "metadata": json.dumps(metadata) if metadata else None
        }
        result = await self._post("Analytics/log", data)
        return "error" not in result

# Global instance
engine_client = EngineClient()
