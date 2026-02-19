import aiohttp
import logging
import asyncio
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

STON_API_URL = "https://api.ston.fi/v1/pools"
API_TIMEOUT = 10
MAX_RETRIES = 3

async def fetch_top_ston_pools() -> List[Dict]:
    """Fetch top STON.fi pools with retry logic and proper async handling"""
    for attempt in range(MAX_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{STON_API_URL}?limit=5",
                    timeout=aiohttp.ClientTimeout(total=API_TIMEOUT)
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"STON.fi API returned status {resp.status}")
                        if attempt < MAX_RETRIES - 1:
                            continue
                        return []
                    data = await resp.json()
                    return [
                        {
                            "token0": pool.get("token0_symbol", "Unknown"),
                            "token1": pool.get("token1_symbol", "Unknown"),
                            "tvl_usd": pool.get("tvl", 0),
                            "apr": pool.get("apr", 0),
                            "link": f"https://ston.fi/pools/{pool.get('address', '')}"
                        } for pool in data.get("pools", [])
                    ]
        except asyncio.TimeoutError:
            logger.warning(f"STON.fi API timeout (attempt {attempt + 1}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)
                continue
        except Exception as e:
            logger.error(f"STON.fi API error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)
                continue
    logger.error(f"Failed to fetch STON.fi pools after {MAX_RETRIES} attempts")
    return []