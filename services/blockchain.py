import asyncio
import logging
import os
from redis import Redis
from typing import List, Dict, Any
from datetime import datetime, timedelta
from utils.redis_conn import redis_client

# Setup logging
logger = logging.getLogger(__name__)


async def get_recent_transactions(address: str, limit: int = 10) -> List[Dict]:
    """Fetch recent transactions for a TON address (async wrapper around tonapi)."""
    try:
        from services.tonapi import get_transactions
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: get_transactions(address, limit))
        if data and isinstance(data.get("transactions"), list):
            return data["transactions"]
        return []
    except Exception as e:
        logger.warning(f"get_recent_transactions for {address}: {e}")
        return []


def is_large_transaction(tx: Dict, threshold_ton: float = 1000.0) -> bool:
    """Return True if transaction amount meets or exceeds threshold (in TON)."""
    amount_ton = tx.get("amount_ton")
    if amount_ton is not None:
        try:
            return float(amount_ton) >= threshold_ton
        except (TypeError, ValueError):
            pass
    # Fallback: extract from transaction structure if present
    if "transaction_id" in tx and isinstance(tx["transaction_id"], dict):
        # Raw API may not have amount_ton; treat as small if unknown
        return False
    return False


def format_transaction_for_notification(tx: Dict) -> Dict[str, Any]:
    """Format transaction data for user notification."""
    tx_id = tx.get("transaction_id") or {}
    hash_val = tx_id.get("hash", "") if isinstance(tx_id, dict) else ""
    return {
        "hash": hash_val,
        "amount_ton": tx.get("amount_ton"),
        "usd_value": tx.get("usd_value"),
        "timestamp": tx.get("timestamp_formatted") or tx.get("now"),
    }


async def notify_followers(address: str, formatted_tx: Dict) -> None:
    """Notify users who follow this address (Redis set wallet_followers:{address} -> telegram ids)."""
    try:
        key = f"wallet_followers:{address}"
        follower_ids = redis_client.smembers(key)
        if not follower_ids:
            return
        # Optional: send via bot if available
        try:
            from main import bot
            if bot:
                text = (
                    f"🐋 Large transaction on followed address {address[:8]}...\n"
                    f"Amount: {formatted_tx.get('amount_ton', 'N/A')} TON\n"
                    f"Hash: {formatted_tx.get('hash', '')[:16]}..."
                )
                for fid in follower_ids:
                    try:
                        await bot.send_message(chat_id=int(fid), text=text)
                    except Exception as e:
                        logger.debug(f"Notify follower {fid}: {e}")
        except ImportError:
            logger.info(f"Wallet notification (no bot): {address} tx {formatted_tx.get('hash', '')}")
    except Exception as e:
        logger.error(f"notify_followers for {address}: {e}")


def cleanup_blockchain_resources() -> None:
    """Release any blockchain-related resources (no-op for now)."""
    pass


async def monitor_followed_wallets():
    """Background task to check followed TON wallets for large transactions"""
    logger.info("Starting wallet monitoring service...")
    
    while True:
        try:
            # Get all tracked TON addresses from Redis
            addresses = redis_client.smembers("tracked_addresses")
            
            if not addresses:
                logger.info("No addresses to monitor")
                await asyncio.sleep(60)
                continue
                
            logger.info(f"Monitoring {len(addresses)} TON addresses")
            
            for address in addresses:
                try:
                    # Get recent transactions for this address
                    transactions = await get_recent_transactions(address, limit=10)
                    
                    if not transactions:
                        logger.debug(f"No recent transactions for {address}")
                        continue
                    
                    # Check each transaction for large amounts
                    for tx in transactions:
                        try:
                            # Check if we've already processed this transaction
                            tx_hash = tx.get('transaction_id', {}).get('hash', '')
                            if not tx_hash:
                                continue
                                
                            # Use Redis to track processed transactions
                            tx_key = f"processed_tx:{tx_hash}"
                            if redis_client.exists(tx_key):
                                continue
                                
                            # Check if it's a large transaction
                            if is_large_transaction(tx, threshold_ton=1000.0):
                                logger.info(f"Large transaction detected for {address}: {tx_hash}")
                                
                                # Format transaction data for notification
                                formatted_tx = format_transaction_for_notification(tx)
                                
                                # Notify followers
                                await notify_followers(address, formatted_tx)
                                
                                # Mark transaction as processed (expire after 24 hours)
                                redis_client.setex(tx_key, 86400, "processed")
                                
                        except Exception as tx_error:
                            logger.error(f"Error processing transaction for {address}: {tx_error}")
                            continue
                            
                except Exception as addr_error:
                    logger.error(f"Error monitoring address {address}: {addr_error}")
                    continue
                    
            # Wait before next check cycle
            await asyncio.sleep(60)  # Check every minute
            
        except Exception as e:
            logger.error(f"Critical monitoring error: {e}")
            await asyncio.sleep(10)  # Short delay before retrying

async def monitor_specific_address(address: str, duration_minutes: int = 60):
    """Monitor a specific address for a limited time"""
    logger.info(f"Starting focused monitoring for {address} for {duration_minutes} minutes")
    
    end_time = asyncio.get_event_loop().time() + (duration_minutes * 60)
    
    while asyncio.get_event_loop().time() < end_time:
        try:
            transactions = await get_recent_transactions(address, limit=5)
            
            for tx in transactions:
                if is_large_transaction(tx):
                    formatted_tx = format_transaction_for_notification(tx)
                    logger.info(f"Large transaction found: {formatted_tx}")
                    
            await asyncio.sleep(30)  # Check every 30 seconds for focused monitoring
            
        except Exception as e:
            logger.error(f"Error in focused monitoring: {e}")
            await asyncio.sleep(10)
            
    logger.info(f"Focused monitoring completed for {address}")

async def add_address_to_monitoring(address: str) -> bool:
    """Add a TON address to monitoring list"""
    try:
        redis_client.sadd("tracked_addresses", address)
        logger.info(f"Added {address} to monitoring")
        return True
    except Exception as e:
        logger.error(f"Error adding address to monitoring: {e}")
        return False

async def remove_address_from_monitoring(address: str) -> bool:
    """Remove a TON address from monitoring list"""
    try:
        redis_client.srem("tracked_addresses", address)
        logger.info(f"Removed {address} from monitoring")
        return True
    except Exception as e:
        logger.error(f"Error removing address from monitoring: {e}")
        return False

async def get_monitored_addresses() -> List[str]:
    """Get list of currently monitored addresses"""
    try:
        return list(redis_client.smembers("tracked_addresses"))
    except Exception as e:
        logger.error(f"Error getting monitored addresses: {e}")
        return []

async def cleanup_and_shutdown():
    """Clean up resources before shutdown"""
    logger.info("Cleaning up monitoring resources...")
    await cleanup_blockchain_resources()
    logger.info("Monitoring service shutdown complete")

if __name__ == "__main__":
    try:
        asyncio.run(monitor_followed_wallets())
    except KeyboardInterrupt:
        logger.info("Monitoring service stopped by user")
    finally:
        asyncio.run(cleanup_and_shutdown())