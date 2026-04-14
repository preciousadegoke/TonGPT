import logging
from typing import Any, Dict, Optional

from utils.redis_conn import redis_client

logger = logging.getLogger(__name__)


async def notify_followers(address: str, formatted_tx: Dict[str, Any], bot: Optional[Any] = None) -> None:
    """
    Notify users who follow `address` about a large transaction.

    `formatted_tx` must contain:
      - `amount_ton`
      - `hash`
    """
    try:
        key = f"wallet_followers:{address}"
        follower_ids = redis_client.smembers(key)
        if not follower_ids:
            return

        if bot is None:
            # Import lazily to avoid import cycles.
            from core.bot_instance import bot as shared_bot

            bot = shared_bot

        if bot is None:
            logger.info("Wallet notification (no bot instance set) for %s", address)
            return

        text = (
            f"🐋 Large transaction on followed address {address[:8]}...\n"
            f"Amount: {formatted_tx.get('amount_ton', 'N/A')} TON\n"
            f"Hash: {str(formatted_tx.get('hash', ''))[:16]}..."
        )

        for fid in follower_ids:
            try:
                chat_id = int(fid.decode() if isinstance(fid, (bytes, bytearray)) else fid)
                await bot.send_message(chat_id=chat_id, text=text)
            except Exception as e:
                logger.debug("notify_followers send failed for %s: %s", fid, e)
    except Exception as e:
        logger.error("notify_followers for %s failed: %s", address, e)

