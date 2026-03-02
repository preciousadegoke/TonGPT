import os
import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

def load_config() -> Dict[str, Any]:
    """Load and validate environment configuration"""
    
    # Get required tokens
    BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    PAYMENT_TOKEN = os.getenv("PAYMENT_TOKEN")
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    TON_API_KEY = os.getenv("TON_API_KEY")
    
    # X API credentials
    X_API_KEY = os.getenv("X_API_KEY")
    X_API_SECRET = os.getenv("X_API_SECRET")
    X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
    X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET")
    X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")
    
    # Redis configuration
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
    
    # Mini-app configuration
    MINIAPP_PORT = int(os.getenv("MINIAPP_PORT", 8000))
    MINIAPP_HOST = os.getenv("MINIAPP_HOST", "0.0.0.0")
    
    # Subscription system configuration — no default in production
    WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
    if not WEBHOOK_SECRET and os.getenv("ENVIRONMENT", "development").lower() == "production":
        logger.critical("WEBHOOK_SECRET must be set in production")
        raise ValueError("WEBHOOK_SECRET is required in production")
    WEBHOOK_SECRET = WEBHOOK_SECRET or ""
    
    # Anti-Bot & Economic Guardrails
    FREE_USER_LIFETIME_AI_QUERIES = int(os.getenv("FREE_USER_LIFETIME_AI_QUERIES", 50))
    GPT_DAILY_SPEND_LIMIT = float(os.getenv("GPT_DAILY_SPEND_LIMIT", 10.0))
    CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "*").split(",")

    return {
        "BOT_TOKEN": BOT_TOKEN,
        "PAYMENT_TOKEN": PAYMENT_TOKEN,
        "OPENROUTER_API_KEY": OPENROUTER_API_KEY,
        "OPENAI_API_KEY": OPENAI_API_KEY,
        "TON_API_KEY": TON_API_KEY,
        "X_API_KEY": X_API_KEY,
        "X_API_SECRET": X_API_SECRET,
        "X_ACCESS_TOKEN": X_ACCESS_TOKEN,
        "X_ACCESS_TOKEN_SECRET": X_ACCESS_TOKEN_SECRET,
        "X_BEARER_TOKEN": X_BEARER_TOKEN,
        "REDIS_HOST": REDIS_HOST,
        "REDIS_PORT": REDIS_PORT,
        "REDIS_PASSWORD": REDIS_PASSWORD,
        "REDIS_URL": REDIS_URL,
        "MINIAPP_PORT": MINIAPP_PORT,
        "MINIAPP_HOST": MINIAPP_HOST,
        "WEBHOOK_SECRET": WEBHOOK_SECRET,
        "FREE_USER_LIFETIME_AI_QUERIES": FREE_USER_LIFETIME_AI_QUERIES,
        "GPT_DAILY_SPEND_LIMIT": GPT_DAILY_SPEND_LIMIT,
        "CORS_ALLOWED_ORIGINS": CORS_ALLOWED_ORIGINS,
    }

def validate_config(config: Dict[str, Any]) -> bool:
    """Validate required configuration"""
    missing_vars = []
    
    if not config["BOT_TOKEN"]:
        missing_vars.append("BOT_TOKEN or TELEGRAM_BOT_TOKEN")
    
    # Check for AI API keys
    if not config["OPENROUTER_API_KEY"] and not config["OPENAI_API_KEY"]:
        missing_vars.append("OPENROUTER_API_KEY or OPENAI_API_KEY")
    
    if missing_vars:
        logger.critical(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
        return False
    
    # Optional warnings
    if not config["PAYMENT_TOKEN"]:
        logger.warning("⚠ PAYMENT_TOKEN not found — Telegram Stars payments will be disabled")
    if not config["TON_API_KEY"]:
        logger.warning("⚠ TON_API_KEY not found — TON API rate limits may apply")
    if not all([config["X_API_KEY"], config["X_API_SECRET"], config["X_BEARER_TOKEN"]]):
        logger.warning("⚠ X API credentials incomplete — X features will be limited")
    
    return True