import aiohttp
import asyncio
import logging
import os
import json
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)

ENGINE_API_KEY = os.getenv("ENGINE_API_KEY", "")

# PAY-011: bound every Engine HTTP call so a hung Engine can't stall the caller
# (e.g. the TON monitor, which awaits activation serially). Default 10s total.
try:
    _ENGINE_TIMEOUT = aiohttp.ClientTimeout(total=float(os.getenv("ENGINE_HTTP_TIMEOUT", "10")))
except (TypeError, ValueError):
    _ENGINE_TIMEOUT = aiohttp.ClientTimeout(total=10)


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
        # REL-002: one shared session (connection pooling, keep-alive) instead of a
        # new ClientSession per request. Created lazily on first use inside the
        # running event loop; closed via close() on shutdown.
        self._session: Optional[aiohttp.ClientSession] = None

    def _headers(self) -> Dict[str, str]:
        """Headers for Engine API (API key is always required)."""
        return {
            "Authorization": f"Bearer {ENGINE_API_KEY}",
            "Content-Type": "application/json",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return the shared session, (re)creating it if missing or closed."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_ENGINE_TIMEOUT)
        return self._session

    async def close(self) -> None:
        """Close the shared session. Call on application shutdown."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _get(self, endpoint: str, extra_headers: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """Internal helper for GET requests"""
        headers = self._headers()
        if extra_headers:
            headers.update(extra_headers)
        session = await self._get_session()
        try:
            async with session.get(f"{self.base_url}/{endpoint}", headers=headers) as response:
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
        session = await self._get_session()
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

    async def _delete(self, endpoint: str, extra_headers: Optional[Dict[str, str]] = None) -> bool:
        """Internal helper for DELETE requests. Returns True if status 200."""
        headers = self._headers()
        if extra_headers:
            headers.update(extra_headers)
        session = await self._get_session()
        try:
            async with session.delete(f"{self.base_url}/{endpoint}", headers=headers) as response:
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

    @staticmethod
    def _user_action_header(telegram_id: int, action: str) -> Dict[str, str]:
        """Mint the SEC-001 per-user assertion the Engine requires for sensitive
        GDPR actions. Best-effort: if the signing secret is unset we send nothing
        and the Engine falls back to its configured behaviour (warn/allow)."""
        try:
            from core.security import make_user_action_assertion
            return {"X-User-Assertion": make_user_action_assertion(telegram_id, action)}
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not mint user-action assertion (%s): %s", action, e)
            return {}

    async def export_user_data(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Export all user data (GDPR data portability). Returns dict or None.

        Bound to ``telegram_id`` via a signed assertion (SEC-001) so a leaked API
        key alone cannot export an arbitrary user's data.
        """
        return await self._get(
            f"User/export/{telegram_id}",
            extra_headers=self._user_action_header(telegram_id, "export"),
        )

    async def delete_user_data(self, telegram_id: int) -> bool:
        """Delete or anonymize user data (GDPR right to erasure). Bound to
        ``telegram_id`` via a signed assertion (SEC-001)."""
        return await self._delete(
            f"User/data/{telegram_id}",
            extra_headers=self._user_action_header(telegram_id, "delete"),
        )

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
            "plan": plan,
            "credits": 0,
            "expiry": result.get("Expiry") or result.get("expiry"),
        }

    async def complete_payment(
        self,
        telegram_id: Any,
        plan: str,
        provider: str,
        external_id: str,
        duration_days: int = 30,
        amount_ton: float = 0.0,
        amount_stars: int = 0,
        max_attempts: int = 3,
        checkout_reference: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically record a payment AND activate the subscription (Postgres SoT).

        This is the ONE canonical activation path. The C# endpoint:
          * validates the paid amount against the canonical price (so a free or
            underpaid activation is impossible — pass the real ``amount_ton`` for
            TON providers and ``amount_stars`` for telegram_stars), and
          * uses the unique index on (ExternalId, Provider) as the single
            idempotency authority, so calling this repeatedly with the same
            external_id is ALWAYS safe -- duplicates return already_processed=True
            without double-activating. That is what lets the durable queue retry.

        Returns a normalized dict:
            ok                 -- True if Postgres confirmed activation
            already_processed  -- True if this was a duplicate
            status             -- "Activated" / "AlreadyProcessed"
            payment_id, plan, expiry
            permanent          -- True => do NOT retry/queue (4xx, e.g. underpayment)
            error              -- present when ok is False
        Never raises.
        """
        data = {
            "telegramId": str(telegram_id),
            "plan": plan,
            "provider": provider,
            "externalId": external_id or "",
            "durationDays": int(duration_days),
            "amountTon": float(amount_ton),
            "amountStars": int(amount_stars),
            **({'checkoutReference': checkout_reference} if checkout_reference else {}),
        }
        last_error: Any = None
        for attempt in range(1, max_attempts + 1):
            try:
                result = await self._post("Payment/complete", data)
            except Exception as e:  # _post shouldn't raise, but be defensive
                last_error = str(e)
                result = {"error": "exception", "message": str(e)}

            if "error" not in result:
                return {
                    "ok": True,
                    "already_processed": bool(result.get("alreadyProcessed")),
                    "status": result.get("status"),
                    "payment_id": str(result.get("paymentId")) if result.get("paymentId") else None,
                    "plan": result.get("plan"),
                    "expiry": result.get("expiry"),
                    "permanent": False,
                }

            last_error = result.get("error")
            # 4xx client errors (e.g. invalid plan) are permanent -- don't retry.
            if isinstance(last_error, int) and 400 <= last_error < 500:
                logger.error(
                    "complete_payment permanent failure user=%s plan=%s: %s",
                    telegram_id, plan, result.get("message"),
                )
                return {
                    "ok": False, "permanent": True,
                    "error": last_error, "message": result.get("message"),
                }

            if attempt < max_attempts:
                await asyncio.sleep(min(8.0, 0.5 * (2 ** attempt)))

        logger.warning(
            "complete_payment transient failure user=%s plan=%s after %s attempts: %s",
            telegram_id, plan, max_attempts, last_error,
        )
        return {"ok": False, "permanent": False, "error": last_error or "unreachable"}

    # NOTE: record_payment(), upgrade_user() and activate_subscription() were
    # REMOVED. They drove the deleted, amount-blind /Payment/record and
    # /Subscription/upgrade endpoints. The single activation path is
    # complete_payment() above.

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
