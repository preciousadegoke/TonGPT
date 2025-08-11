# services/trending_scanner.py

import aiohttp

TONAPI_TRENDING_URL = "https://tonapi.io/v2/trending/memecoins"  # Example endpoint (mock)

async def fetch_trending_memecoins(api_key: str):
    headers = {
        "Authorization": f"Bearer {api_key}"
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.get(TONAPI_TRENDING_URL) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    print(f"TONAPI trending fetch failed with status: {resp.status}")
                    return {}
        except aiohttp.ClientError as e:
            print(f"Error fetching trending memecoins: {e}")
            return {}
