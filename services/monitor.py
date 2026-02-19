import asyncio
import logging
from redis import Redis
from typing import List, Dict, Any

# Initialize Redis client
redis_client = Redis(host='localhost', port=6379, decode_responses=True)

# Setup logging
logger = logging.getLogger(__name__)

# Import or define these functions based on your project structure
from .blockchain import get_recent_transactions, is_large_transaction
from .notifications import notify_followers

async def monitor_followed_wallets():
    """Background task to check followed wallets"""
    while True:
        try:
            addresses = redis_client.smembers("tracked_addresses")
            for address in addresses:
                transactions = get_recent_transactions(address)
                for tx in transactions:
                    if is_large_transaction(tx):  # > $1,000
                        await notify_followers(address, tx)
            await asyncio.sleep(60)  # Check every minute
        except Exception as e:
            logger.error(f"Monitoring error: {e}")

if __name__ == "__main__":
    asyncio.run(monitor_followed_wallets())