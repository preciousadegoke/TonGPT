import os
import aiohttp
import asyncio
import logging
import json
from typing import Optional, List, Dict, Any
from .prompts import SYSTEM_PROMPT, get_enhanced_context, AI_RESPONSE_DISCLAIMER
from utils.realtime_data import get_realtime_context

# §1.1 — Redis-backed conversation history so memory survives restarts/redeploys.
# Import is guarded: if Redis (or its module) is unavailable, the engine falls
# back transparently to the in-process dict and nothing breaks.
try:
    from utils.redis_conn import redis_client as _redis_client
except Exception:  # pragma: no cover - defensive
    _redis_client = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# §1.1 tunables
HISTORY_MAX = 20                 # keep at most the last 20 messages (10 turns)
HISTORY_TTL = 7 * 24 * 60 * 60   # expire idle histories after 7 days
_HISTORY_KEY = "chat:hist:{user_id}"

# §MEM — rolling conversation summary. When old turns fall off the end of the
# raw history window they are folded into a compact summary instead of being
# forgotten, so the bot keeps long-term context (user's tokens of interest,
# risk appetite, open questions) at near-zero token cost. Summarization runs
# fire-and-forget on a cheap model and NEVER adds latency to a user turn.
_SUMMARY_KEY = "chat:sum:{user_id}"
SUMMARY_TTL = 30 * 24 * 60 * 60          # remember for 30 idle days
SUMMARY_MAX_CHARS = 1500                 # hard cap on stored summary size
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "meta-llama/llama-3.1-8b-instruct")
_SUMMARY_PROMPT = (
    "You maintain a compact memory profile of a Telegram user chatting with a "
    "TON-blockchain AI assistant. Merge the EXISTING MEMORY with the NEW "
    "CONVERSATION EXCERPT into an updated memory. Keep only durable, useful "
    "facts: tokens/projects they follow, their experience level and risk "
    "appetite, preferences (language, verbosity), and unresolved questions. "
    "Drop chit-chat and anything stale or contradicted. Write terse bullet "
    "points, max 150 words, no preamble."
)

class GPTEngine:
    """
    Robust, asynchronous engine for GPT interactions.
    Supports OpenRouter and OpenAI.
    """
    
    def __init__(self, api_key: Optional[str] = None, model: str = "meta-llama/llama-3.1-8b-instruct"):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.conversation_history: Dict[int, List[Dict]] = {}
        # §MEM — per-user rolling summary + in-flight guard (one summarization
        # task per user at a time; overflow is re-queued on the next trim).
        self.conversation_summary: Dict[int, str] = {}
        self._summary_inflight: set = set()
        
        # Determine provider based on API key format or explict config
        if not self.api_key:
             logger.warning("No API key provided for GPTEngine")
        elif not self.api_key.startswith("sk-or-"):
            # Assume OpenAI if not OpenRouter key
            self.base_url = "https://api.openai.com/v1/chat/completions"
            self.model = "gpt-4" if "gpt-4" in model else "gpt-3.5-turbo"

    # ------------------------------------------------------------------ #
    # §1.1 — Redis persistence helpers.
    # The Redis client is synchronous, so every call is offloaded to a
    # worker thread to avoid blocking the event loop. All calls are wrapped
    # so a Redis outage degrades to in-process memory instead of crashing.
    # ------------------------------------------------------------------ #
    @staticmethod
    def _history_key(user_id: int) -> str:
        return _HISTORY_KEY.format(user_id=user_id)

    async def _load_history(self, user_id: int) -> List[Dict]:
        """Hydrate a user's recent history from Redis (cold-start restore)."""
        if not _redis_client:
            return []
        key = self._history_key(user_id)
        try:
            raw = await asyncio.to_thread(_redis_client.lrange, key, -HISTORY_MAX, -1)
        except Exception as e:
            logger.warning(f"History load failed for {user_id}: {e}")
            return []

        history: List[Dict] = []
        for item in raw or []:
            try:
                msg = json.loads(item)
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    history.append(msg)
            except Exception:
                continue  # skip a corrupt entry rather than fail the turn
        return history

    async def _persist_turn(self, user_id: int, user_msg: Dict, assistant_msg: Dict) -> None:
        """Append the latest turn to Redis, trim to HISTORY_MAX, refresh TTL."""
        if not _redis_client:
            return
        key = self._history_key(user_id)

        def _write():
            _redis_client.rpush(key, json.dumps(user_msg), json.dumps(assistant_msg))
            _redis_client.ltrim(key, -HISTORY_MAX, -1)
            _redis_client.expire(key, HISTORY_TTL)

        try:
            await asyncio.to_thread(_write)
        except Exception as e:
            logger.warning(f"History persist failed for {user_id}: {e}")

    # ------------------------------------------------------------------ #
    # §MEM — rolling summary helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _summary_key(user_id: int) -> str:
        return _SUMMARY_KEY.format(user_id=user_id)

    async def _load_summary(self, user_id: int) -> str:
        if user_id in self.conversation_summary:
            return self.conversation_summary[user_id]
        summary = ""
        if _redis_client:
            try:
                raw = await asyncio.to_thread(_redis_client.get, self._summary_key(user_id))
                if raw:
                    summary = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
            except Exception as e:
                logger.warning(f"Summary load failed for {user_id}: {e}")
        self.conversation_summary[user_id] = summary
        return summary

    async def _save_summary(self, user_id: int, summary: str) -> None:
        summary = (summary or "").strip()[:SUMMARY_MAX_CHARS]
        self.conversation_summary[user_id] = summary
        if not _redis_client:
            return
        try:
            def _write():
                key = self._summary_key(user_id)
                if summary:
                    _redis_client.set(key, summary, ex=SUMMARY_TTL)
                else:
                    _redis_client.delete(key)
            await asyncio.to_thread(_write)
        except Exception as e:
            logger.warning(f"Summary persist failed for {user_id}: {e}")

    def _schedule_summary_update(self, user_id: int, overflow: List[Dict]) -> None:
        """Fold trimmed-off turns into the rolling summary, off the hot path."""
        if not overflow or user_id in self._summary_inflight:
            return
        self._summary_inflight.add(user_id)

        async def _run():
            try:
                await self._update_summary(user_id, overflow)
            except Exception as e:  # never propagate — memory is best-effort
                logger.warning(f"Summary update failed for {user_id}: {e}")
            finally:
                self._summary_inflight.discard(user_id)

        try:
            asyncio.get_running_loop().create_task(_run())
        except RuntimeError:
            self._summary_inflight.discard(user_id)

    async def _update_summary(self, user_id: int, overflow: List[Dict]) -> None:
        existing = await self._load_summary(user_id)
        excerpt = "\n".join(
            f"{m.get('role', '?')}: {str(m.get('content', ''))[:500]}" for m in overflow
        )[:4000]
        messages = [
            {"role": "system", "content": _SUMMARY_PROMPT},
            {"role": "user", "content": (
                f"EXISTING MEMORY:\n{existing or '(none)'}\n\n"
                f"NEW CONVERSATION EXCERPT:\n{excerpt}"
            )},
        ]
        new_summary = await self._raw_completion(messages, model=SUMMARY_MODEL, max_tokens=300)
        if new_summary:
            await self._save_summary(user_id, new_summary)

    async def _raw_completion(self, messages: List[Dict], model: str, max_tokens: int = 300) -> Optional[str]:
        """Bare-bones completion call (no history/system-context side effects)."""
        if not self.api_key:
            return None
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if "openrouter" in self.base_url:
            headers["HTTP-Referer"] = "https://tongpt.bot"
            headers["X-Title"] = "TonGPT Bot"
        payload = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_url, headers=headers, json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status != 200:
                        logger.warning(f"raw completion HTTP {response.status}")
                        return None
                    result = await response.json()
                    choices = result.get("choices") or []
                    if not choices:
                        return None
                    return (choices[0].get("message", {}).get("content") or "").strip() or None
        except Exception as e:
            logger.warning(f"raw completion failed: {e}")
            return None

    # ------------------------------------------------------------------ #
    # LAUNCH-FIX 3 — explicit health check with real diagnostics.
    # ------------------------------------------------------------------ #
    async def health_check(self) -> tuple:
        """One cheap completion call. Returns (ok, detail) where detail names
        the endpoint, model, HTTP status and body head on failure — the boot
        log previously showed only 'connection test failed' with no cause."""
        if not self.api_key:
            return False, "no API key (OPENROUTER_API_KEY / OPENAI_API_KEY unset)"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if "openrouter" in self.base_url:
            headers["HTTP-Referer"] = "https://tongpt.bot"
            headers["X-Title"] = "TonGPT Bot"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_url, headers=headers, json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    body = await resp.text()
                    if resp.status == 200:
                        return True, f"HTTP 200 (endpoint={self.base_url}, model={self.model})"
                    return False, (
                        f"HTTP {resp.status} (endpoint={self.base_url}, model={self.model}): "
                        f"{body[:300]}"
                    )
        except asyncio.TimeoutError:
            return False, f"timeout after 15s connecting to {self.base_url}"
        except aiohttp.ClientError as e:
            return False, f"connection error to {self.base_url}: {type(e).__name__}: {e}"
        except Exception as e:  # noqa: BLE001
            return False, f"unexpected {type(e).__name__}: {e}"

    # ------------------------------------------------------------------ #
    # §MEM — public memory API (used by /memory and /forget)
    # ------------------------------------------------------------------ #
    async def get_memory_summary(self, user_id: int) -> str:
        """What the bot remembers about this user (may be empty)."""
        return await self._load_summary(user_id)

    async def clear_memory(self, user_id: int) -> None:
        """Erase conversation history AND the rolling summary for a user."""
        self.conversation_history.pop(user_id, None)
        self.conversation_summary.pop(user_id, None)
        if not _redis_client:
            return
        try:
            def _wipe():
                _redis_client.delete(self._history_key(user_id))
                _redis_client.delete(self._summary_key(user_id))
            await asyncio.to_thread(_wipe)
        except Exception as e:
            logger.warning(f"Memory clear failed for {user_id}: {e}")

    async def generate_response(self, user_message: str, user_id: int = 0, context_override: str = None, model_override: str = None) -> str:
        """
        Generate a response from GPT with full context awareness.
        
        Args:
            user_message: The user's input/question.
            user_id: User ID for conversation history (0 for stateless).
            context_override: Optional system prompt override.
            model_override: Specify an exact model bypassing default settings.
            
        Returns:
            The AI's response text.
        """
        if not self.api_key:
            return "⚠️ API configuration error. Please contact admin."

        try:
            # 1. Build Context
            realtime_context = get_realtime_context()
            enhanced_context = get_enhanced_context(user_message)
            
            # Combine into system prompt
            system_prompt = context_override or SYSTEM_PROMPT.format(
                realtime_context=f"{realtime_context}\n\n{enhanced_context}"
            )
            
            # 2. Build Message Chain
            messages = [{"role": "system", "content": system_prompt}]

            # Add history if applicable
            if user_id != 0:
                if user_id not in self.conversation_history:
                    # Cold start for this user in this process: restore from Redis
                    # so memory survives restarts/redeploys (§1.1).
                    self.conversation_history[user_id] = await self._load_history(user_id)
                # §MEM — inject the rolling long-term summary (facts older than
                # the raw history window) so the model keeps context cheaply.
                summary = await self._load_summary(user_id)
                if summary:
                    messages[0]["content"] += (
                        "\n\n--- Long-term memory about this user (from earlier "
                        "conversations; may be incomplete) ---\n" + summary
                    )
                # Add last 10 messages from history
                messages.extend(self.conversation_history[user_id][-10:])
            
            messages.append({"role": "user", "content": user_message})
            
            # 3. Prepare Request
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            # Add OpenRouter specific headers
            if "openrouter" in self.base_url:
                headers["HTTP-Referer"] = "https://tongpt.bot"
                headers["X-Title"] = "TonGPT Bot"
            
            payload = {
                "model": model_override or self.model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 1000,
                "presence_penalty": 0.1,
                "frequency_penalty": 0.1
            }
            
            # 4. Execute Async Request
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=45)
                ) as response:
                    
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"GPT API Error {response.status}: {error_text}")
                        return self._handle_api_error(response.status)
                        
                    result = await response.json()
                    
                    if not result.get("choices"):
                        return "⚠️ Received empty response from AI provider."
                        
                    answer = result["choices"][0]["message"]["content"].strip()
                    
                    # AI Safety Middleware
                    lower_answer = answer.lower()
                    risky_phrases = ["guaranteed profit", "100x", "sure thing", "can't lose", "definitely go up", "will pump"]
                    if any(phrase in lower_answer for phrase in risky_phrases):
                        answer = "⚠️ **AI Safety Notice:** This response originally contained deterministic financial language and has been flagged. Cryptocurrency markets are highly volatile.\n\n" + answer
                        logger.warning(f"AI Safety filter triggered for user {user_id}")
                    
                    # Append compliance disclaimer to every AI response
                    answer = answer.rstrip() + AI_RESPONSE_DISCLAIMER

                    # 5. Update History (in-process + Redis §1.1)
                    if user_id != 0:
                        user_msg = {"role": "user", "content": user_message}
                        assistant_msg = {"role": "assistant", "content": answer}
                        self.conversation_history[user_id].extend([user_msg, assistant_msg])
                        # Trim in-process copy — and fold the overflow into the
                        # rolling summary instead of forgetting it (§MEM).
                        if len(self.conversation_history[user_id]) > HISTORY_MAX:
                            overflow = self.conversation_history[user_id][:-HISTORY_MAX]
                            self.conversation_history[user_id] = self.conversation_history[user_id][-HISTORY_MAX:]
                            self._schedule_summary_update(user_id, overflow)
                        # Durably persist the turn (trims + sets TTL server-side)
                        await self._persist_turn(user_id, user_msg, assistant_msg)

                    return answer

        except asyncio.TimeoutError:
            logger.error("GPT Request timed out")
            return "⚠️ Request timed out. Please try again."
        except Exception as e:
            logger.error(f"Unexpected GPT error: {e}")
            return "⚠️ An unexpected error occurred. Please try again later."

    def _handle_api_error(self, status_code: int) -> str:
        if status_code == 401:
            return "⚠️ Authentication error. Please contact admin."
        elif status_code == 429:
            return "⚠️ Too many requests. Please try again in a moment."
        elif status_code == 502:
            return "⚠️ AI Service temporarily unavailable. Please try again."
        return "⚠️ Network error. Please try again later."

# Global singleton instance
_engine_instance = None

def get_engine() -> GPTEngine:
    """Get or create global engine instance"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = GPTEngine()
    return _engine_instance

# Backward compatibility wrapper
async def ask_gpt(prompt: str, model: str = None, context: str = None, user_id: int = 0) -> str:
    """Legacy wrapper for backward compatibility"""
    engine = get_engine()
    # Check if we need to temporarily update model/context only for this call? 
    # For simplicity, we just use the robust engine as is, ignoring model unless critcal.
    # The new engine handles context dynamically.
    return await engine.generate_response(prompt, user_id=user_id, context_override=context, model_override=model)

async def test_gpt_connection() -> bool:
    """Startup health check. LAUNCH-FIX 3: logs the ACTUAL failure (HTTP
    status + response body head, or the exception) instead of a bare False,
    so '❌ GPT connection test failed' is never opaque again."""
    ok, detail = await get_engine().health_check()
    if ok:
        logger.info(f"GPT health check passed: {detail}")
    else:
        logger.error(f"GPT health check FAILED: {detail}")
    return ok