import requests

async def scan_memecoins(limit: int):
    try:
        response = requests.get(f"https://toncenter.com/api/v2/getTokens?limit={limit}").json()
        return [
            {
                "symbol": token["symbol"],
                "change": token["price_change_24h"],
                "price": token["price_usd"]
            } for token in response["tokens"]
        ]
    except Exception as e:
        print(f"Scanner Error: {e}")
        return []