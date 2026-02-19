import os
import aiohttp
import asyncio
import logging
import json
from typing import Optional, List, Dict, Any
from .prompts import SYSTEM_PROMPT, get_enhanced_context
from utils.realtime_data import get_realtime_context

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GPTEngine:
    """
    Robust, asynchronous engine for GPT interactions.
    Supports OpenRouter and OpenAI.
    """
    
    def __init__(self, api_key: Optional[str] = None, model: str = "openai/gpt-4"):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.conversation_history: Dict[int, List[Dict]] = {}
        
        # Determine provider based on API key format or explict config
        if not self.api_key:
             logger.warning("No API key provided for GPTEngine")
        elif not self.api_key.startswith("sk-or-"):
            # Assume OpenAI if not OpenRouter key
            self.base_url = "https://api.openai.com/v1/chat/completions"
            self.model = "gpt-4" if "gpt-4" in model else "gpt-3.5-turbo"
            
    async def generate_response(self, user_message: str, user_id: int = 0, context_override: str = None) -> str:
        """
        Generate a response from GPT with full context awareness.
        
        Args:
            user_message: The user's input/question.
            user_id: User ID for conversation history (0 for stateless).
            context_override: Optional system prompt override.
            
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
                    self.conversation_history[user_id] = []
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
                "model": self.model,
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
                    
                    # 5. Update History
                    if user_id != 0:
                        self.conversation_history[user_id].extend([
                            {"role": "user", "content": user_message},
                            {"role": "assistant", "content": answer}
                        ])
                        # Trim history
                        if len(self.conversation_history[user_id]) > 20:
                            self.conversation_history[user_id] = self.conversation_history[user_id][-20:]
                            
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
async def ask_gpt(prompt: str, model: str = None, context: str = None) -> str:
    """Legacy wrapper for backward compatibility"""
    engine = get_engine()
    # Check if we need to temporarily update model/context only for this call? 
    # For simplicity, we just use the robust engine as is, ignoring model unless critcal.
    # The new engine handles context dynamically.
    return await engine.generate_response(prompt, user_id=0, context_override=context)

async def test_gpt_connection() -> bool:
    """Test connection"""
    try:
        engine = get_engine()
        response = await engine.generate_response("Test", user_id=0, context_override="Reply 'OK'")
        return "OK" in response
    except:
        return False