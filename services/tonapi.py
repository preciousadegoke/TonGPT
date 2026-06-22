"""
services/tonapi.py — BACKWARD-COMPAT ASYNC SHIM.

The real implementation now lives in services/ton_api_service.py, which uses a
single shared httpx.AsyncClient and is fully non-blocking. Previously this module
used synchronous `requests` + `time.sleep()` inside async handlers, which blocked
the entire event loop.

IMPORTANT: every function here is now an ASYNC coroutine. Call them with `await`.
If you have old code doing `asyncio.to_thread(get_large_transactions, ...)` or
`run_in_executor(..., get_transactions)`, replace it with a direct `await` — the
functions are already async and non-blocking.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from services.ton_api_service import TonApiError, ton_service  # noqa: F401 (re-export)

logger = logging.getLogger(__name__)


async def get_ton_price_usd() -> float:
    """STRICT TON/USD price for payments. Raises if no fresh-enough price."""
    return await ton_service.get_ton_price_usd()


async def get_ton_price_best_effort() -> float:
    """Non-strict price for display; returns last known or 0.0, never raises."""
    return await ton_service.get_ton_price_best_effort()


async def get_wallet_info(address: str, user_id: Optional[int] = None) -> dict:
    return await ton_service.get_wallet_info(address, user_id)


async def get_jettons(address: str, user_id: Optional[int] = None) -> dict:
    return await ton_service.get_jettons(address, user_id)


async def get_transactions(address: str, limit: int = 10, user_id: Optional[int] = None) -> dict:
    return await ton_service.get_transactions(address, limit, user_id)


async def get_wallet_transactions(address: str, limit: int = 10, user_id: Optional[int] = None) -> dict:
    """Alias for get_transactions (backward compatibility)."""
    return await ton_service.get_transactions(address, limit, user_id)


async def resolve_dns(domain: str) -> dict:
    return await ton_service.resolve_dns(domain)


async def get_large_transactions(limit: int = 50, min_amount: float = 1000.0) -> List[Dict]:
    return await ton_service.get_large_transactions(limit=limit, min_amount=min_amount)


async def get_whale_summary(hours: int = 24) -> Dict:
    return await ton_service.get_whale_alert_summary(hours=hours)


async def test_ton_api_connection() -> Dict:
    """Async health probe. NOTE: now a coroutine — callers must `await`."""
    return await ton_service.test_connection()


__all__ = [
    "TonApiError", "ton_service",
    "get_ton_price_usd", "get_ton_price_best_effort",
    "get_wallet_info", "get_jettons", "get_transactions", "get_wallet_transactions",
    "resolve_dns", "get_large_transactions", "get_whale_summary", "test_ton_api_connection",
]
