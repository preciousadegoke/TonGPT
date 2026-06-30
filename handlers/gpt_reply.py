# handlers/gpt_reply.py - FIXED
# Handles /ask command, general text messages, and catch-all for unmatched messages.
# This module MUST be registered LAST in HANDLER_MODULES (main.py) because it
# contains the catch-all @router.message() handler.

import re

import structlog
from aiogram import F, Router, types
from aiogram.filters import Command
from gpt.engine import ask_gpt

logger = structlog.get_logger(__name__)

# Create router for this module
router = Router()

MAX_INPUT = 2000


def sanitize_user_input(text: str) -> str:
    """Trim and length-cap user input.

    GPT-002: we deliberately do NOT try to strip "prompt-injection" phrases. A
    3-phrase regex blocklist is trivially bypassed (rewording, other languages,
    spacing, encoding), gives false confidence, and can mangle legitimate text.
    Real injection defense lives at the system-prompt / tool-permission level,
    not in string filtering — so this just bounds the length.
    """
    if not text:
        return ""
    return text.strip()[:MAX_INPUT]


async def _moderation_allows(message: types.Message, text: str, user_id: int) -> bool:
    """Content-moderation gate. Returns True if the message may proceed to GPT.

    Part of the main error flow: any failure to even reach the moderation
    service is caught here and treated as ALLOW (fail-open), so the bot never
    goes down because moderation is unavailable. When content is blocked, the
    user gets a friendly reply and we return False.
    """
    try:
        from services.moderation_service import moderate_text
        result = await moderate_text(text, user_id=user_id)
    except Exception as e:
        # Last-resort guard (e.g. import error). FAIL CLOSED (MOD-001/GPT-001):
        # if we cannot even reach moderation, block rather than emit unmoderated
        # AI output. A persistent failure here is a deploy error the startup
        # readiness check (report_startup_status) is designed to surface.
        logger.critical("moderation_unavailable_blocking", user_id=user_id, err=str(e), exc_info=True)
        await message.reply(
            "⚠️ Our safety check is temporarily unavailable, so I can't process this "
            "right now. Please try again shortly."
        )
        return False

    # Log every outcome clearly: warnings for flagged content, info otherwise.
    log = logger.warning if result.flagged else logger.info
    log(
        "moderation_checked",
        user_id=user_id,
        allowed=result.allowed,
        flagged=result.flagged,
        categories=result.categories,
        error=result.error,
    )

    if not result.allowed:
        await message.reply(result.user_message or "🚫 Sorry, I can't help with that request.")
        return False
    return True


async def _handle_gpt_query_impl(message: types.Message):
    """Handle GPT queries from users with comprehensive error handling (inner impl for rate-limit decorator)."""
    try:
        # Handle both /ask command and general messages
        if message.text.startswith('/ask'):
            question_raw = message.text.replace('/ask', '').strip()
        else:
            question_raw = message.text.strip()
        question = sanitize_user_input(question_raw)
        
        if not question:
            await message.reply("❌ Please provide a question after /ask")
            return

        user_id = message.from_user.id

        # ---- Safety gate: content moderation must pass before we call GPT ----
        if not await _moderation_allows(message, question, user_id):
            return

        try:
            await message.bot.send_chat_action(message.chat.id, "typing")
        except Exception as e:
            logger.warning("send_chat_action_failed", err=str(e))
        
        # Risk Scoring and Model Downgrading
        model_override = None
        # user_id already resolved above for the moderation gate.

        try:
            from core.rate_limiter import get_rate_limiter
            limiter = get_rate_limiter()
            if limiter:
                ip_address = getattr(message, "_ip_address", None)
                # GPT-003: reuse the tier the rate-limit decorator already resolved
                # (cached on the limiter for this request) instead of making a
                # second get_user_status round-trip to the Engine.
                from core.rate_limiter import _resolve_tier
                tier = await _resolve_tier(limiter, user_id)

                risk_score, risk_tier = await limiter.get_user_risk_score(user_id, tier, ip_address)
                
                if risk_tier == "High Risk":
                    await message.reply("⚠️ Your account is temporarily restricted due to suspicious activity. Please verify your account.")
                    logger.warning("blocked_high_risk_user", user_id=user_id, risk_score=risk_score)
                    return
                elif risk_tier == "Suspicious":
                    model_override = "openai/gpt-4o-mini"
                    logger.warning("downgraded_suspicious_user", user_id=user_id, risk_score=risk_score, model=model_override)
                elif risk_tier == "Watch":
                    logger.info("watch_user_active", user_id=user_id, risk_score=risk_score)
        except Exception as e:
            logger.debug("risk_evaluation_skipped", err=str(e))

        # Get response from GPT with timeout
        try:
            response = await ask_gpt(question, model=model_override, user_id=user_id)
        except Exception as e:
            await message.reply("🚫 Error processing your request. Please try again later.")
            logger.error("gpt_request_error", user_id=user_id, err=str(e), exc_info=True)
            return
        
        if response:
            # MOD-002: screen the MODEL OUTPUT, not just the input. A jailbreak
            # that slips past input moderation could still elicit harmful text;
            # we re-check the generated response and refuse to send flagged
            # content. (We block only on a genuine category hit — a transient
            # moderation outage doesn't nuke a response whose INPUT already
            # passed moderation upstream.)
            try:
                from services.moderation_service import moderate_text
                out_mod = await moderate_text(response, user_id=user_id)
                if out_mod.flagged and not out_mod.allowed:
                    logger.warning("gpt_output_blocked", user_id=user_id, categories=out_mod.categories)
                    await message.reply(out_mod.user_message or "🚫 I can't share that response.")
                    return
            except Exception as e:
                logger.error("output_moderation_error", user_id=user_id, err=str(e))

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
                        logger.error("message_part_send_failed", part=i + 1, err=str(e))
            else:
                await message.reply(response)
        else:
            await message.reply("⚠️ No response generated. Please try again.")
            
    except Exception as e:
        logger.error("gpt_query_unexpected_error", err=str(e), exc_info=True)
        try:
            await message.reply("❌ An unexpected error occurred. Please try again later.")
        except Exception as send_error:
            logger.error("error_message_send_failed", err=str(send_error))

# Rate-limit the GPT endpoint (the most expensive call we make).
#
# P0 FIX: the decorator resolves the LIVE limiter at *call time* (see
# core/rate_limiter.create_rate_limit_decorator), so applying it here at import
# time — before the limiter singleton is created — is safe and correct.
#
# The previous implementation checked get_rate_limiter() at import time, found
# None (the limiter was created later in on_startup), and silently shipped this
# handler with NO rate limiting at all. That is now impossible.
from core.rate_limiter import create_rate_limit_decorator

handle_gpt_query = create_rate_limit_decorator("ai_queries")(_handle_gpt_query_impl)

# Register command handler
@router.message(Command("ask"))
async def ask_command(message: types.Message):
    await handle_gpt_query(message)

# Register general message handler (for non-command messages)
@router.message(F.text & ~F.text.startswith('/'))
async def handle_general_message(message: types.Message):
    """Handle all non-command messages with GPT"""
    await handle_gpt_query(message)


# P0-FIX-4: Catch-all handler for unrecognized commands and any other unmatched messages.
# This MUST be registered last (gpt_reply is already last in HANDLER_MODULES).
# Without this, unknown /commands like /foobar get silently dropped.
@router.message()
async def catch_all_handler(message: types.Message):
    """Catch-all: reply to any message not matched by earlier handlers."""
    text = (message.text or "").strip()
    if text.startswith("/"):
        # Unknown command
        cmd = text.split()[0]  # e.g. "/foobar"
        await message.reply(
            f"❓ <b>Unknown command:</b> <code>{cmd}</code>\n\n"
            "💡 Use /help to see all available commands.",
            parse_mode="HTML",
        )
    else:
        # Non-text or media message we can't handle — acknowledge
        await message.reply(
            "🤖 I can only process text messages.\n"
            "💡 Use /help to see available commands.",
        )


# Registration function for main.py
def register_gpt_reply_handlers(dp):
    dp.include_router(router)
