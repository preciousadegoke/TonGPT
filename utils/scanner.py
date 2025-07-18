import requests

def fetch_trending_tokens(limit=5):
    try:
        url = "https://api.ston.fi/v1/tokens/search"
        response = requests.get(url, timeout=10)
        data = response.json()

        # Filter top trending meme-like tokens
        trending = []
        for token in data:
            if (
                token.get("is_verified") is False  # Many meme tokens aren't verified
                and token.get("symbol")  # Ensure it has a symbol
                and token.get("price_usd") is not None
            ):
                trending.append({
                    "symbol": token["symbol"],
                    "price": round(token["price_usd"], 6),
                    "volume": int(token.get("daily_volume_usd", 0)),
                    "change": round(token.get("price_change24h", 0), 2)
                })

        # Sort by volume or % change
        trending.sort(key=lambda x: x["volume"], reverse=True)
        return trending[:limit]

    except Exception as e:
        print(f"[Scanner Error] {e}")
        return []
