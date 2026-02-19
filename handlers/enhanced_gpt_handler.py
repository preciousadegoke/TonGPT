import logging
import asyncio
from aiogram import types
from typing import Optional
from gpt.engine import get_engine

logger = logging.getLogger(__name__)

class EnhancedGPTHandler:
    """
    Wrapper for the centralized GPTEngine to maintain backward compatibility
    with existing handler calls.
    """
    def __init__(self, api_key: str, model: str = "openai/gpt-4"):
        # Initialize the global engine instance with provided credentials
        self.engine = get_engine()
        # Update engine config if not already set (or override)
        if hasattr(self.engine, 'api_key') and not self.engine.api_key:
             self.engine.api_key = api_key
        
    async def get_comprehensive_response(self, user_message: str, user_id: int) -> str:
        """Delegate generation to the core engine"""
        return await self.engine.generate_response(user_message, user_id)

async def handle_gpt_query(message: types.Message, gpt_handler: EnhancedGPTHandler):
    """Handle comprehensive GPT queries"""
    try:
        user_message = message.text
        user_id = message.from_user.id
        
        # Show typing action
        await message.bot.send_chat_action(message.chat.id, "typing")
        
        # Get comprehensive response
        response = await gpt_handler.get_comprehensive_response(user_message, user_id)
        
        # Send response (split if too long)
        if len(response) > 4000:
            chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
            for chunk in chunks:
                await message.answer(chunk, parse_mode="HTML", disable_web_page_preview=True)
        else:
            await message.answer(response, parse_mode="HTML", disable_web_page_preview=True)
            
    except Exception as e:
        logger.error(f"Error handling GPT query: {e}")
        await message.answer("⚠️ Sorry, I encountered an error processing your request. Please try again.")

async def test_gpt_connection(api_key: str = None) -> bool:
    """Test GPT API connection"""
    try:
        engine = get_engine()
        # Update key if provided
        if api_key:
            engine.api_key = api_key
            
        response = await engine.generate_response("Test", user_id=0, context_override="Reply 'OK'")
        return bool(response and "⚠️" not in response)
    except:
        return False
