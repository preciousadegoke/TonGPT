"""
core/env_guard.py — Centralized environment variable validation (C-14).

Call validate_required_env_vars() at the very start of main.py,
before any other project imports, to get a single clear error
listing every missing variable instead of scattered KeyErrors.
"""
import os
from typing import List


# Variables that MUST be set for the bot to function.
# Add new required vars here as the project grows.
REQUIRED_ENV_VARS: List[str] = [
    "BOT_TOKEN",
    "ENGINE_API_KEY",
]


def validate_required_env_vars() -> None:
    """
    Check all required environment variables and raise a single
    EnvironmentError listing every missing variable by name.
    
    Call this once at startup, after dotenv is loaded but before
    any service module is imported.
    """
    missing = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}. "
            f"Set them in .env or your deployment config."
        )
