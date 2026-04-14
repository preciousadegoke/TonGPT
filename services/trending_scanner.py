import aiohttp
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TONAPI_JETTONS_URL = "https://tonapi.io/v2/jettons"


async def fetch_trending_memecoins(api_key: str) -> List[Dict[str, Any]]:
    """
    Fetch "trending" jettons by sorting by `holders_count`.

    TonAPI does not provide a stable `/v2/trending/memecoins` endpoint, so we use the
    real `/v2/jettons` endpoint and sort locally.
    """
    headers: Dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        try:
            async with session.get(TONAPI_JETTONS_URL, params={"limit": 20}) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(
                        "TONAPI trending fetch failed: status=%s body=%s",
                        resp.status,
                        body[:300],
                    )
                    return []

                data = await resp.json()
        except aiohttp.ClientError as e:
            logger.error("Error fetching trending memecoins: %s", e)
            return []
        except Exception as e:
            logger.error("Unexpected trending memecoins error: %s", e)
            return []

    # Best-effort extraction of the jettons list.
    jettons = None
    if isinstance(data, list):
        jettons = data
    elif isinstance(data, dict):
        jettons = data.get("jettons") or data.get("items") or data.get("data") or []

    if not isinstance(jettons, list):
        return []

    def holders_count(item: Dict[str, Any]) -> int:
        val = item.get("holders_count") or item.get("holders") or 0
        try:
            return int(val)
        except (TypeError, ValueError):
            return 0

    sorted_jettons = sorted(jettons, key=holders_count, reverse=True)
    return sorted_jettons[:10]
