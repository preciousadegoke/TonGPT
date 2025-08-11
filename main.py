import asyncio
import logging
import os
from pathlib import Path
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path=Path('.') / '.env')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Get BOT_TOKEN and PAYMENT_TOKEN
BOT_TOKEN = os.getenv("BOT_TOKEN")
PAYMENT_TOKEN = os.getenv("PAYMENT_TOKEN")
if not BOT_TOKEN:
    logger.critical("❌ BOT_TOKEN is missing in your .env file.")
    raise ValueError("BOT_TOKEN is required in your .env file")
if not PAYMENT_TOKEN:
    logger.critical("❌ PAYMENT_TOKEN is missing in your .env file.")
    raise ValueError("PAYMENT_TOKEN is required in your .env file")

# Global configuration
config = {"PAYMENT_TOKEN": PAYMENT_TOKEN}

# Initialize bot and dispatcher
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

# Register core commands
from bot.commands import register_commands
register_commands(dp, config)

# Register additional handlers
external_modules = {
    "alerts": "register_alerts_handlers",
    "wallet_watch": "register_wallet_handlers",
    "scan": "register_scan_handlers",
    "ston": "register_ston_handlers",
    "follow": "register_follow_handlers",
    "influencer_handler": "register_influencer_handlers",
    "pay": "register_pay_handlers",
    "trending": "register_trending_handlers",
    "whale": "register_whale_handlers",
}

for module, register_func in external_modules.items():
    try:
        imported = __import__(f"handlers.{module}", fromlist=[register_func])
        getattr(imported, register_func)(dp)
        logger.info(f"✅ Registered handler: {module}")
    except (ImportError, AttributeError) as e:
        logger.warning(f"⚠️ Could not load {module}: {e}")

# Start the bot
async def main():
    logger.info("🤖 TonGPT is now running with Aiogram.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.exception(f"🚨 TonGPT crashed: {e}")