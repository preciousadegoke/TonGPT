import requests

async def fetch_top_ston_pools():
    try:
        response = requests.get("https://api.ston.fi/v1/pools?limit=5").json()
        return [
            {
                "token0": pool["token0_symbol"],
                "token1": pool["token1_symbol"],
                "tvl_usd": pool["tvl"],
                "apr": pool["apr"],
                "link": f"https://ston.fi/pools/{pool['address']}"
            } for pool in response["pools"]
        ]
    except Exception as e:
        print(f"STON.fi API Error: {e}")
        return []