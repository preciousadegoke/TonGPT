"""
core/bot_instance.py — Shared Bot singleton to break circular import.

Usage:
  In main.py after creating the bot:
      from core.bot_instance import set_bot
      set_bot(ctx.bot)

  In any service that needs the bot:
      from core.bot_instance import bot
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot

bot: "Bot | None" = None


def set_bot(instance: "Bot") -> None:
    """Store the bot instance so services can access it without importing main."""
    global bot
    bot = instance


def get_bot() -> "Bot | None":
    """Return the shared bot instance (or None if not yet initialized).

    Prefer this over importing the module-level ``bot`` directly, since the
    function always reads the current value rather than a stale binding.
    """
    return bot
