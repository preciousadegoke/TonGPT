# handlers/gpt_reply.py - FIXED
import logging
from aiogram import Router, types
from aiogram.filters import Command
from gpt.engine import ask_gpt

logger = logging.getLogger(__name__)

# Create router for this module
router = Router()

async def handle_gpt_query(message: types.Message):
    """Handle GPT queries from users with comprehensive error handling"""
    try:
        # Handle both /ask command and general messages
        if message.text.startswith('/ask'):
            question = message.text.replace('/ask', '').strip()
        else:
            question = message.text.strip()
        
        if not question:
            await message.reply("❌ Please provide a question after /ask")
            return
        
        try:
            await message.bot.send_chat_action(message.chat.id, "typing")
        except Exception as e:
            logger.warning(f"Failed to send chat action: {e}")
        
        # Get response from GPT with timeout
        try:
            response = await ask_gpt(question)
        except TimeoutError:
            await message.reply("⏱️ Request timed out. Please try again.")
            logger.error(f"GPT request timeout for user {message.from_user.id}")
            return
        except Exception as e:
            await message.reply("🚫 Error processing your request. Please try again later.")
            logger.error(f"GPT request error for user {message.from_user.id}: {e}", exc_info=True)
            return
        
        if response:
            # Split long messages
            if len(response) > 4000:
                parts = [response[i:i+4000] for i in range(0, len(response), 4000)]
                for i, part in enumerate(parts):
                    try:
                        if i == 0:
                            await message.reply(part)
                        else:
                            await message.answer(part)
                    except Exception as e:
                        logger.error(f"Failed to send message part {i+1}: {e}")
            else:
                await message.reply(response)
        else:
            await message.reply("⚠️ No response generated. Please try again.")
            
    except Exception as e:
        logger.error(f"Unexpected error in GPT query handler: {e}", exc_info=True)
        try:
            await message.reply("❌ An unexpected error occurred. Please try again later.")
        except Exception as send_error:
            logger.error(f"Failed to send error message: {send_error}")
        await message.reply("❌ Error processing your request. Please try again.")

# Register command handler
@router.message(Command("ask"))
async def ask_command(message: types.Message):
    await handle_gpt_query(message)

# Register general message handler (for non-command messages)
@router.message()
async def handle_general_message(message: types.Message):
    """Handle all non-command messages with GPT"""
    if message.text and not message.text.startswith('/'):
        await handle_gpt_query(message)

# Registration function for main.py
def register_gpt_reply_handlers(dp):
    dp.include_router(router)