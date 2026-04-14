import asyncio
import logging
import os
from redis import Redis
from typing import List, Dict, Any
from datetime import datetime, timedelta

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
    """Backward-compatible wrapper around `services.alerts.notify_followers`."""
    from services.alerts import notify_followers as _notify_followers

    await _notify_followers(address, formatted_tx)


def cleanup_blockchain_resources() -> None:
    """Release any blockchain-related resources (no-op for now)."""
    pass
