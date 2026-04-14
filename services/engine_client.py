import aiohttp
import logging
import os
import json
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)

ENGINE_API_KEY = os.getenv("ENGINE_API_KEY", "")


class EngineServerError(Exception):
    """Raised when the Engine API returns a 5xx server error."""



class EngineClient:
    """
    Client for interactions with the C# TonGPT.Engine API.
    Acts as the single source of truth for data persistence, replacing local databases.
    """
    
    def __init__(self, base_url: str = None):
        if base_url:
            self.base_url = base_url.rstrip('/')
        else:
            self.base_url = os.getenv("ENGINE_URL", "http://localhost:5090/api").rstrip('/')

    def _headers(self) -> Dict[str, str]:
        """Headers for Engine API (API key is always required)."""
        return {
            "Authorization": f"Bearer {ENGINE_API_KEY}",
            "Content-Type": "application/json",
        }

    async def _get(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Internal helper for GET requests"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{self.base_url}/{endpoint}", headers=self._headers()) as response:
                    if response.status == 200:
                        return await response.json()
                    if response.status == 404:
                        return None
                    if 500 <= response.status < 600:
                        text = await response.text()
                        logger.error("Engine API GET %s failed with %s: %s", endpoint, response.status, text)
                        raise EngineServerError(f"Engine GET {endpoint} -> {response.status}")
                    logger.warning(f"Engine API GET {endpoint} failed: {response.status}")
                    return {}
            except EngineServerError:
                raise
            except Exception as e:
                logger.error(f"Engine API connection failed: {e}")
                raise EngineServerError("Engine unreachable") from e


    async def _post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Internal helper for POST requests"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(f"{self.base_url}/{endpoint}", json=data, headers=self._headers()) as response:
                    if response.status in [200, 201]:
                        return await response.json()
                    
                    error_text = await response.text()
                    logger.warning(f"Engine API POST {endpoint} failed: {response.status} - {error_text}")
                    return {"error": response.status, "message": error_text}
            except Exception as e:
                logger.error(f"Engine API connection failed: {e}")
                return {"error": "connection_failed"}

    async def _delete(self, endpoint: str) -> bool:
        """Internal helper for DELETE requests. Returns True if status 200."""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.delete(f"{self.base_url}/{endpoint}", headers=self._headers()) as response:
                    return response.status == 200
            except Exception as e:
                logger.error(f"Engine API DELETE {endpoint} failed: {e}")
                return False

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

    async def export_user_data(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Export all user data (GDPR data portability). Returns dict or None."""
        return await self._get(f"User/export/{telegram_id}")

    async def delete_user_data(self, telegram_id: int) -> bool:
        """Delete or anonymize user data (GDPR right to erasure)."""
        return await self._delete(f"User/data/{telegram_id}")

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
        Raises EngineServerError if the engine is unreachable (L-10).
        """
        try:
            result = await self._get(f"Chat/history/{telegram_id}?limit={limit}")

            # If API is not ready or returns empty, return empty list
            if not result or not isinstance(result, list):
                return []

            # Convert to OpenAI format
            context = []
            for msg in result:
                if "userMessage" in msg:
                    context.append({"role": "user", "content": msg["userMessage"]})
                if "aiResponse" in msg:
                    context.append({"role": "assistant", "content": msg["aiResponse"]})

            return context
        except EngineServerError:
            raise  # let caller handle engine unavailability
        except Exception as e:
            logger.error("get_chat_context failed for %s: %s", telegram_id, e)
            return []

    # ==========================================
    # Subscription & Payments
    # ==========================================

    async def get_user_status(self, telegram_id: str) -> Dict[str, Any]:
        """Check user subscription status"""
        try:
            result = await self._get(f"Subscription/status/{telegram_id}")
        except EngineServerError:
            return {"tier": "error", "credits": 0, "error": "engine_unavailable"}
        if not result:
            return {"tier": "free", "credits": 0}
        plan = (result.get("Plan") or result.get("plan") or "Free")
        return {
            "tier": plan,
            "credits": 0,
            "expiry": result.get("Expiry") or result.get("expiry"),
        }

    async def record_payment(self, telegram_id: str, plan: str, provider: str, external_id: str = None) -> Optional[str]:
        """Record a completed payment. Returns payment_id (guid string) for use in upgrade_user."""
        data = {
            "telegramId": str(telegram_id),
            "plan": plan,
            "provider": provider,
            "externalId": external_id or "",
        }
        result = await self._post("Payment/record", data)
        if "error" in result:
            return None
        pid = result.get("paymentId")
        return str(pid) if pid else None

    async def upgrade_user(self, telegram_id: str, plan: str, payment_record_id: str = None) -> bool:
        """Upgrade user plan. Requires payment_record_id from record_payment (payment verification)."""
        payload = {
            "telegramId": str(telegram_id),
            "plan": plan,
        }
        if payment_record_id:
            payload["paymentRecordId"] = payment_record_id
        result = await self._post("Subscription/upgrade", payload)
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
