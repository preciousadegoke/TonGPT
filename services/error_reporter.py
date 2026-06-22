"""
services/error_reporter.py — Telegram Error Channel Reporter

Sends structured exception summaries to a private Telegram channel.
Gracefully degrades to log-only when ERROR_CHANNEL_ID is not configured.

Success criteria:
  ✓ Errors forwarded to Telegram channel within seconds.
  ✓ Rate-limited: max 1 message per RATE_LIMIT_SECONDS per unique error key.
  ✓ No-op (log warning once) if ERROR_CHANNEL_ID env var is missing.
  ✓ Never raises — all internal failures are swallowed and logged.

Usage:
  from services.error_reporter import error_reporter
  await error_reporter.report(exc, context="whale_handler", user_id=123)
"""

import html
import os
import time
import traceback
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class ErrorReporter:
    """Forwards exceptions to a private Telegram error channel.

    Fully robust:
      - Graceful degradation when ERROR_CHANNEL_ID is missing (log once, then silent).
      - Per-error-type rate limiting (keyed on exc class + context) to prevent floods.
      - Never raises; all internal failures are swallowed and logged.
    """

    # Class-level defaults
    RATE_LIMIT_SECONDS: int = 10  # min gap between messages for same error key
    MAX_TRACKED_KEYS: int = 500   # cap on rate-limit dict size to prevent memory leak

    def __init__(self, bot=None, channel_id: Optional[int] = None):
        self._bot = bot
        raw_id = channel_id or os.environ.get("ERROR_CHANNEL_ID")
        try:
            self._channel_id: Optional[int] = int(raw_id) if raw_id else None
        except (ValueError, TypeError):
            logger.warning(
                "error_reporter_bad_channel_id",
                raw_id=raw_id,
                hint="ERROR_CHANNEL_ID must be an integer (e.g. -100123456789)",
            )
            self._channel_id = None

        # {rate_key: last_sent_monotonic_timestamp}
        self._last_sent: dict[str, float] = {}
        self._warned_no_channel: bool = False

    # -- Public API ----------------------------------------------------------

    def set_bot(self, bot) -> None:
        """Late-bind the Bot instance (called after Bot is created in main)."""
        self._bot = bot

    async def report(
        self,
        exc: BaseException,
        *,
        context: str = "",
        user_id: Optional[int] = None,
    ) -> None:
        """
        Report an exception to the error channel.

        Args:
            exc: The exception instance.
            context: Free-text label (e.g. "whale_handler", "on_startup").
            user_id: Telegram user ID involved, if any.

        This method **never raises**. All internal failures are swallowed and logged.
        """
        try:
            await self._report_impl(exc, context=context, user_id=user_id)
        except Exception as inner:
            # Never propagate — error reporting must not crash the bot
            logger.warning(
                "error_reporter_internal_failure",
                inner_exc=f"{type(inner).__name__}: {inner}",
            )

    # -- Internals -----------------------------------------------------------

    async def _report_impl(
        self,
        exc: BaseException,
        *,
        context: str,
        user_id: Optional[int],
    ) -> None:
        # Guard: channel not configured — warn once, then silent
        if not self._channel_id:
            if not self._warned_no_channel:
                logger.warning(
                    "error_channel_not_configured",
                    hint="Set ERROR_CHANNEL_ID in .env to enable Telegram error alerts.",
                )
                self._warned_no_channel = True
            return

        # Guard: bot not wired yet
        if not self._bot:
            logger.debug("error_reporter_no_bot", hint="Bot not set yet — skipping report")
            return

        # Rate-limit by (exception class + context) to allow different contexts
        # of the same exception type to each get reported independently.
        exc_class = type(exc).__qualname__
        rate_key = f"{exc_class}::{context}" if context else exc_class
        now = time.monotonic()
        last = self._last_sent.get(rate_key, 0.0)
        if now - last < self.RATE_LIMIT_SECONDS:
            logger.debug(
                "error_reporter_rate_limited",
                rate_key=rate_key,
                seconds_since_last=round(now - last, 1),
            )
            return

        # Evict oldest entries if dict grows too large (prevent unbounded memory)
        if len(self._last_sent) >= self.MAX_TRACKED_KEYS:
            oldest_key = min(self._last_sent, key=self._last_sent.get)
            del self._last_sent[oldest_key]

        self._last_sent[rate_key] = now

        # Build HTML message
        tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        tb_text = "".join(tb_lines)[-1500:]  # Truncate to fit Telegram limits

        parts = [
            "🚨 <b>TonGPT Error Report</b>\n",
            f"<b>Type:</b> <code>{html.escape(exc_class)}</code>",
            f"<b>Message:</b> <code>{html.escape(str(exc)[:300])}</code>",
        ]
        if context:
            parts.append(f"<b>Context:</b> {html.escape(context)}")
        if user_id is not None:
            parts.append(f"<b>User:</b> <code>{user_id}</code>")
        parts.append(
            f"\n<b>Traceback (last 1500 chars):</b>\n<pre>{html.escape(tb_text)}</pre>"
        )

        message = "\n".join(parts)

        # Send (await to catch errors, but never propagate)
        try:
            await self._bot.send_message(
                chat_id=self._channel_id,
                text=message[:4096],  # Telegram hard limit
                parse_mode="HTML",
            )
        except Exception as send_err:
            logger.warning(
                "error_reporter_send_failed",
                channel_id=self._channel_id,
                send_err=f"{type(send_err).__name__}: {send_err}",
            )


# ── Singleton ───────────────────────────────────────────────────────────────
# Importable from anywhere: `from services.error_reporter import error_reporter`
error_reporter = ErrorReporter()
