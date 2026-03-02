# handlers/gpt_reply.py - FIXED
import logging
from aiogram import Router, types
from aiogram.filters import Command
from gpt.engine import ask_gpt

logger = logging.getLogger(__name__)

# Create router for this module
router = Router()

async def _handle_gpt_query_impl(message: types.Message):
    """Handle GPT queries from users with comprehensive error handling (inner impl for rate-limit decorator)."""
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
        
        # Risk Scoring and Model Downgrading
        model_override = None
        user_id = message.from_user.id
        
        try:
            from core.rate_limiting import get_rate_limiter
            limiter = get_rate_limiter()
            if limiter:
                ip_address = getattr(message, "_ip_address", None)
                tier = "free"
                try:
                    from services.engine_client import engine_client
                    status = await engine_client.get_user_status(str(user_id))
                    tier = (status.get("plan") or "Free").lower()
                except Exception:
                    pass
                    
                risk_score, risk_tier = await limiter.get_user_risk_score(user_id, tier, ip_address)
                
                if risk_tier == "High Risk":
                    await message.reply("⚠️ Your account is temporarily restricted due to suspicious activity. Please verify your account.")
                    logger.warning(f"BLOCKED High Risk user {user_id} (Score: {risk_score})")
                    return
                elif risk_tier == "Suspicious":
                    model_override = "openai/gpt-4o-mini"
                    logger.warning(f"DOWNGRADED Suspicious user {user_id} (Score: {risk_score}) to {model_override}")
                elif risk_tier == "Watch":
                    logger.info(f"WATCH user {user_id} (Score: {risk_score}) active.")
        except Exception as e:
            logger.debug(f"Risk evaluation skipped: {e}")

        # Get response from GPT with timeout
        try:
            response = await ask_gpt(question, model=model_override, user_id=user_id)
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

# Apply AdvancedRateLimiter via decorator when available (Guardrail 4: rate limit GPT endpoints)
def _wrap_with_rate_limit(handler):
    try:
        from core.rate_limiting import create_rate_limit_decorator, get_rate_limiter
        if get_rate_limiter():
            return create_rate_limit_decorator("ai_queries")(handler)
    except Exception as e:
        logger.debug("Rate limit decorator not applied: %s", e)
    return handler

handle_gpt_query = _wrap_with_rate_limit(_handle_gpt_query_impl)

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