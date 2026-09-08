"""
core/plugin.py — thin CommandPlugin contract for TonGPT bot features (§2.1).

WHY THIS FILE EXISTS
--------------------
Command features (whale, alerts, pay, ...) are already loaded by
``main.register_all_handlers`` via a convention: each ``handlers.<name>``
module exposes either a ``register*(dp[, ctx])`` function or a ``router``
attribute. That convention works but was never written down, so nothing
guarantees a new feature conforms to it or is testable in isolation.

This module *codifies* that existing convention as a lightweight, runtime
checkable ``Protocol`` plus a tiny helper. It intentionally does NOT change
the loader or rewrite any handler — it only gives new features a uniform,
self-documenting shape and a one-line conformance test.

USAGE (new feature)
-------------------
A plugin is any object exposing ``name``, ``commands`` and ``register``::

    from aiogram import Router
    from core.plugin import CommandPlugin

    class WhalePlugin:
        name = "whale"
        commands = ["/whale"]

        def register(self, dp, ctx=None):
            dp.include_router(router)

Existing modules that expose ``register_*`` / ``router`` keep working
unchanged — this Protocol simply describes the same shape.
"""

from __future__ import annotations

from typing import Any, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class CommandPlugin(Protocol):
    """Structural contract every TonGPT command feature should satisfy.

    Attributes
    ----------
    name:
        Short, unique identifier (matches the ``handlers.<name>`` module name).
    commands:
        The bot commands this plugin owns, e.g. ``["/whale", "/info"]``.
        Used for docs/help/registry introspection; not enforced at runtime.
    """

    name: str
    commands: List[str]

    def register(self, dp: Any, ctx: Optional[Any] = ...) -> None:
        """Attach this plugin's handlers/routers to the dispatcher ``dp``.

        Mirrors the existing loader contract: called as ``register(dp, ctx)``
        when a context is available, otherwise ``register(dp)``.
        """
        ...


def is_command_plugin(obj: Any) -> bool:
    """Return True if ``obj`` satisfies the :class:`CommandPlugin` contract.

    A thin helper for conformance tests, e.g.::

        assert is_command_plugin(WhalePlugin())
    """
    return (
        isinstance(obj, CommandPlugin)
        and isinstance(getattr(obj, "name", None), str)
        and isinstance(getattr(obj, "commands", None), list)
        and callable(getattr(obj, "register", None))
    )
