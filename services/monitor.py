import asyncio
import logging
from typing import List, Dict, Any

from utils.redis_conn import redis_client

# Setup logging
logger = logging.getLogger(__name__)

from .blockchain import get_recent_transactions, is_large_transaction
from .notifications import notify_followers


async def monitor_followed_wallets():
    """Background task to check followed wallets using the shared Redis client."""
    while True:
        try:
            addresses = redis_client.smembers("tracked_addresses") if redis_client else set()
            for address in addresses:
                transactions = get_recent_transactions(address)
                for tx in transactions:
                    if is_large_transaction(tx):  # > $1,000
                        await notify_followers(address, tx)
            await asyncio.sleep(60)  # Check every minute
        except Exception as e:
            logger.error(f"Monitoring error: {e}")