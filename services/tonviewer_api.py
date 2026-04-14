"""
Async-safe TON token info fetcher.

Replaces brittle TonViewer HTML scraping with TonAPI structured JSON:
  https://tonapi.io/v2/jettons/{address}
"""

import asyncio
import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

TONAPI_JETTON_URL = "https://tonapi.io/v2/jettons"


def _fetch_token_info(address: str) -> Optional[Dict[str, Any]]:
    """Fetch and normalize token info (runs in a worker thread)."""
    try:
        url = f"{TONAPI_JETTON_URL}/{address}"
        response = requests.get(url, headers={"Accept": "application/json"}, timeout=10)
        if response.status_code != 200:
            return None

        data = response.json() if response.text else {}
        metadata = data.get("metadata") or {}

        name = metadata.get("name") or "Unknown"
        symbol = metadata.get("symbol") or ""

        total_supply = data.get("total_supply")
        holders_count = data.get("holders_count")

        # TonAPI commonly includes pricing in a few possible shapes; keep best-effort without failing.
        price = "N/A"
        if isinstance(data.get("price"), dict):
            price_val = data["price"].get("value") or data["price"].get("amount")
            if price_val is not None:
                price = price_val
        elif data.get("price") is not None:
            price = data.get("price")

        holders = holders_count if holders_count is not None else "N/A"

        return {
            "name": name,
            "symbol": symbol,
            "price": price,
            "holders": holders,
            "total_supply": total_supply,
            "holders_count": holders_count,
        }
    except Exception as e:
        logger.error("[TonAPI token info error] %s", e)
        return None


async def get_token_info_from_tonviewer(address: str) -> Optional[Dict[str, Any]]:
    """Async wrapper for `_fetch_token_info`."""
    return await asyncio.to_thread(_fetch_token_info, address)
