# services/moderation_service.py
"""
OpenAI content-moderation service for TonGPT.

Screens *user input* with OpenAI's free ``omni-moderation-latest`` model BEFORE
it ever reaches the GPT engine, as a first line of defence against hate,
harassment, self-harm, sexual content (incl. minors), violence and illicit
instructions.

Key properties
--------------
* **Never raises** — every failure becomes an allow/deny decision.
* **Fail-open by default** — if moderation is unavailable (no key, SDK missing,
  timeout, outage), the message is ALLOWED through and the event is logged.
  Flip ``MODERATION_FAIL_OPEN=false`` for a strict, fail-closed posture.
* **Structured logging** via ``structlog`` for easy dashboards/alerts.
* **No new dependency** — uses the already-pinned ``openai`` SDK.

The Moderation endpoint needs a real **OpenAI** key (``sk-...``). An OpenRouter
key (``sk-or-...``) will be rejected, so the service reads
``OPENAI_MODERATION_API_KEY`` first (falling back to ``OPENAI_API_KEY``) and
quietly disables itself if neither is a usable OpenAI key.

Run a quick self-test:
    python -m services.moderation_service
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Union

import structlog

logger = structlog.get_logger(__name__)

# --------------------------------------------------------------------------- #
# Optional SDK import (defensive: a missing/broken SDK must never crash the bot)
# --------------------------------------------------------------------------- #
try:
    from openai import (
        APIConnectionError,
        APIError,
        APITimeoutError,
        AsyncOpenAI,
        RateLimitError,
    )

    _SDK_OK = True
except Exception as _err:  # pragma: no cover - defensive
    _SDK_OK = False
    AsyncOpenAI = None  # type: ignore[assignment]
    APIError = APITimeoutError = APIConnectionError = RateLimitError = Exception  # type: ignore
    logger.warning("moderation_sdk_import_failed", err=str(_err))


# --------------------------------------------------------------------------- #
# Config helpers
# --------------------------------------------------------------------------- #
def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _load_block_categories() -> Optional[Set[str]]:
    """Optional allow-list of categories that trigger a block.

    Empty/unset => block on ANY flagged category (the safe default).
    """
    raw = os.getenv("MODERATION_BLOCK_CATEGORIES", "").strip()
    if not raw:
        return None
    return {c.strip() for c in raw.split(",") if c.strip()}


@dataclass
class ModerationConfig:
    """All settings, resolved from the environment at construction time."""

    enabled: bool = field(default_factory=lambda: _env_bool("MODERATION_ENABLED", True))
    model: str = field(
        default_factory=lambda: os.getenv("OPENAI_MODERATION_MODEL", "omni-moderation-latest")
    )
    # Allow the message through when moderation can't run (availability > strictness).
    fail_open: bool = field(default_factory=lambda: _env_bool("MODERATION_FAIL_OPEN", True))
    timeout: float = field(default_factory=lambda: float(os.getenv("MODERATION_TIMEOUT", "8")))
    api_key: str = field(
        default_factory=lambda: (
            os.getenv("OPENAI_MODERATION_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        ).strip()
    )
    block_categories: Optional[Set[str]] = field(default_factory=_load_block_categories)

    @property
    def has_usable_key(self) -> bool:
        # Moderation is OpenAI-only; an OpenRouter key (sk-or-...) won't work.
        return bool(self.api_key) and not self.api_key.startswith("sk-or-")


# --------------------------------------------------------------------------- #
# Result type
# --------------------------------------------------------------------------- #
@dataclass
class ModerationResult:
    """Outcome of a moderation check.

    allowed       -- caller may proceed to GPT.
    flagged       -- OpenAI flagged the content (may still be allowed if a
                     custom block-list excludes the category).
    categories    -- flagged category names.
    scores        -- category -> confidence (0..1), flagged ones only.
    user_message  -- friendly text to show the user when blocked.
    error         -- short reason when the check couldn't run (None on success).
    """

    allowed: bool
    flagged: bool = False
    categories: List[str] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)
    user_message: Optional[str] = None
    error: Optional[str] = None


# --------------------------------------------------------------------------- #
# User-facing messages
# --------------------------------------------------------------------------- #
DEFAULT_BLOCK_MESSAGE = (
    "🚫 Sorry, I can't help with that. Your message was flagged by our safety "
    "filter. Please rephrase your request and try again."
)

# Self-harm uses a supportive tone and points toward help, not a flat refusal.
CATEGORY_MESSAGES: Dict[str, str] = {
    "self-harm": (
        "💛 It sounds like you may be going through something really difficult. "
        "I can't help with this here, but you deserve support. If you're in "
        "immediate danger, please contact your local emergency services, or reach "
        "a trained counselor through a crisis line in your country. You're not alone."
    ),
    "sexual/minors": (
        "🚫 This request involves content that is strictly prohibited and cannot "
        "be processed under any circumstances."
    ),
    "sexual": "🚫 I can't help with sexual or explicit content. Please keep requests appropriate.",
    "hate": "🚫 I can't help with hateful content. Please rephrase respectfully and try again.",
    "harassment": "🚫 I can't help with harassing or abusive content. Please rephrase and try again.",
    "violence": "🚫 I can't help with violent content. Please rephrase your request and try again.",
    "illicit": "🚫 I can't help with requests for illegal activity. Please try a different question.",
}

# Priority for choosing the reply when several categories are flagged.
_MESSAGE_PRIORITY: List[str] = [
    "sexual/minors",
    "self-harm/intent",
    "self-harm/instructions",
    "self-harm",
    "hate/threatening",
    "hate",
    "harassment/threatening",
    "harassment",
    "violence/graphic",
    "violence",
    "illicit/violent",
    "illicit",
    "sexual",
]


def _message_for(categories: List[str]) -> str:
    flagged = set(categories)
    for cat in _MESSAGE_PRIORITY:
        if cat in flagged and cat in CATEGORY_MESSAGES:
            return CATEGORY_MESSAGES[cat]
    for cat in categories:  # fall back from "self-harm/intent" -> "self-harm"
        base = cat.split("/", 1)[0]
        if base in CATEGORY_MESSAGES:
            return CATEGORY_MESSAGES[base]
    return DEFAULT_BLOCK_MESSAGE


def _to_dict(obj) -> Dict[str, object]:
    """Normalise an SDK pydantic model to a dict keyed by OpenAI's canonical
    names (e.g. ``"self-harm/intent"``)."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(by_alias=True)
        except TypeError:  # pragma: no cover - older pydantic
            return obj.model_dump()
    try:
        return dict(obj)
    except Exception:  # pragma: no cover
        return {}


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #
class ModerationService:
    """Stateless-ish wrapper around the OpenAI Moderation API."""

    def __init__(self, config: Optional[ModerationConfig] = None) -> None:
        self.config = config or ModerationConfig()
        self._client: Optional["AsyncOpenAI"] = None  # type: ignore[name-defined]
        self._logged_unavailable = False

    # -- client ------------------------------------------------------------- #
    def _client_or_none(self) -> Optional["AsyncOpenAI"]:  # type: ignore[name-defined]
        if self._client is not None:
            return self._client
        if not _SDK_OK or not self.config.has_usable_key:
            if not self._logged_unavailable:
                logger.warning(
                    "moderation_unavailable",
                    sdk_ok=_SDK_OK,
                    has_usable_key=self.config.has_usable_key,
                    hint="Set OPENAI_MODERATION_API_KEY (sk-...) to enable moderation.",
                )
                self._logged_unavailable = True
            return None
        try:
            self._client = AsyncOpenAI(
                api_key=self.config.api_key,
                timeout=self.config.timeout,
                max_retries=1,
            )
        except Exception as e:  # pragma: no cover - defensive
            logger.error("moderation_client_init_failed", err=str(e))
            return None
        return self._client

    # -- helpers ------------------------------------------------------------ #
    def _degraded(self, error: str) -> ModerationResult:
        if self.config.fail_open:
            return ModerationResult(allowed=True, flagged=False, error=error)
        return ModerationResult(
            allowed=False,
            flagged=False,
            error=error,
            user_message=(
                "⚠️ Our safety check is temporarily unavailable, so I can't process "
                "this request right now. Please try again shortly."
            ),
        )

    def _should_block(self, categories: List[str]) -> bool:
        if not categories:
            return False
        if self.config.block_categories is None:
            return True
        return any(c in self.config.block_categories for c in categories)

    # -- public API --------------------------------------------------------- #
    async def moderate(
        self, text: str, *, user_id: Optional[Union[int, str]] = None
    ) -> ModerationResult:
        if not self.config.enabled:
            logger.debug("moderation_disabled", user_id=user_id)
            return ModerationResult(allowed=True, error="disabled")

        if not text or not text.strip():
            return ModerationResult(allowed=True)

        client = self._client_or_none()
        if client is None:
            return self._degraded("unavailable")

        try:
            resp = await client.moderations.create(model=self.config.model, input=text)
        except APITimeoutError:
            logger.warning("moderation_timeout", user_id=user_id, timeout=self.config.timeout)
            return self._degraded("timeout")
        except RateLimitError:
            logger.warning("moderation_rate_limited", user_id=user_id)
            return self._degraded("rate_limited")
        except (APIConnectionError, APIError) as e:
            logger.error("moderation_api_error", user_id=user_id, err=str(e))
            return self._degraded("api_error")
        except Exception as e:  # pragma: no cover - last-resort guard
            logger.error("moderation_unexpected_error", user_id=user_id, err=str(e), exc_info=True)
            return self._degraded("unexpected")

        try:
            result = resp.results[0]
        except (AttributeError, IndexError):
            logger.error("moderation_empty_response", user_id=user_id)
            return self._degraded("empty_response")

        categories = _to_dict(getattr(result, "categories", None))
        scores = _to_dict(getattr(result, "category_scores", None))
        flagged_categories = [name for name, hit in categories.items() if hit]
        flagged = bool(getattr(result, "flagged", False)) or bool(flagged_categories)
        flagged_scores = {
            name: round(float(scores.get(name, 0.0) or 0.0), 4) for name in flagged_categories
        }

        if self._should_block(flagged_categories):
            logger.warning(
                "moderation_blocked",
                user_id=user_id,
                categories=flagged_categories,
                scores=flagged_scores,
            )
            return ModerationResult(
                allowed=False,
                flagged=True,
                categories=flagged_categories,
                scores=flagged_scores,
                user_message=_message_for(flagged_categories),
            )

        if flagged:
            logger.info(
                "moderation_flagged_allowed",
                user_id=user_id,
                categories=flagged_categories,
                scores=flagged_scores,
            )
            return ModerationResult(
                allowed=True,
                flagged=True,
                categories=flagged_categories,
                scores=flagged_scores,
            )

        logger.debug("moderation_passed", user_id=user_id)
        return ModerationResult(allowed=True)


# --------------------------------------------------------------------------- #
# Module-level singleton + convenience wrappers (what the handler imports)
# --------------------------------------------------------------------------- #
_service: Optional[ModerationService] = None


def get_moderation_service() -> ModerationService:
    global _service
    if _service is None:
        _service = ModerationService()
    return _service


async def moderate_text(
    text: str, *, user_id: Optional[Union[int, str]] = None
) -> ModerationResult:
    """Convenience wrapper used by handlers. Never raises."""
    return await get_moderation_service().moderate(text, user_id=user_id)


async def is_allowed(text: str, *, user_id: Optional[Union[int, str]] = None) -> bool:
    return (await moderate_text(text, user_id=user_id)).allowed


__all__ = [
    "ModerationConfig",
    "ModerationResult",
    "ModerationService",
    "get_moderation_service",
    "moderate_text",
    "is_allowed",
]


# --------------------------------------------------------------------------- #
# Simple self-test:  python -m services.moderation_service
# Needs a real OpenAI key (OPENAI_MODERATION_API_KEY or OPENAI_API_KEY = sk-...).
# With no key + fail-open, both samples are ALLOWED with error="unavailable".
# --------------------------------------------------------------------------- #
async def test_moderation() -> None:
    svc = get_moderation_service()
    print(
        "config:",
        f"enabled={svc.config.enabled}",
        f"model={svc.config.model}",
        f"fail_open={svc.config.fail_open}",
        f"usable_key={svc.config.has_usable_key}",
    )
    samples = [
        ("benign", "What is the current price of Toncoin?"),
        ("harassment", "You are worthless and I will hurt you."),
    ]
    for label, text in samples:
        r = await svc.moderate(text, user_id="selftest")
        print(
            f"[{label:11}] allowed={r.allowed} flagged={r.flagged} "
            f"categories={r.categories} error={r.error}"
        )


if __name__ == "__main__":
    asyncio.run(test_moderation())
