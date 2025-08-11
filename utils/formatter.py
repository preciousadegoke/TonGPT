from datetime import datetime

def format_token_info(token: dict) -> str:
    """
    Formats token data into a user-friendly string.
    """
    name = token.get("name", "Unknown")
    symbol = token.get("symbol", "")
    price = token.get("price_usd", "N/A")
    market_cap = token.get("market_cap_usd", "N/A")
    change = token.get("percent_change_24h", "N/A")
    
    return (
        f"🪙 <b>{name} ({symbol})</b>\n"
        f"💵 Price: <code>${price:.4f}</code>\n"
        f"📈 24h Change: <code>{change}%</code>\n"
        f"🏦 Market Cap: <code>${market_cap:,}</code>"
    )

def format_sentiment(score: float) -> str:
    """
    Formats sentiment score into emojis and label.
    """
    if score > 0.5:
        return f"😄 Positive ({score:.2f})"
    elif score < -0.5:
        return f"😠 Negative ({score:.2f})"
    else:
        return f"😐 Neutral ({score:.2f})"

def format_wallet_summary(wallet: dict) -> str:
    """
    Formats wallet tracking summary.
    """
    address = wallet.get("address", "N/A")
    balance = wallet.get("balance_ton", 0)
    tokens = wallet.get("tokens", [])

    summary = f"📬 Wallet: <code>{address}</code>\n💰 TON Balance: <b>{balance} TON</b>\n"

    if tokens:
        summary += "\n📦 <b>Tokens:</b>\n"
        for token in tokens:
            summary += f"- {token['symbol']}: {token['balance']}\n"
    else:
        summary += "No tokens found."

    return summary

def format_timestamp(ts: int) -> str:
    """
    Converts UNIX timestamp to readable date-time string.
    """
    return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S UTC")

def format_trending_tokens(tokens: list) -> str:
    """
    Formats a list of trending tokens.
    """
    if not tokens:
        return "No trending tokens right now."

    result = "<b>🔥 Trending Memecoins</b>\n"
    for idx, token in enumerate(tokens[:10], 1):
        result += f"{idx}. <b>{token['symbol']}</b> - ${token['price_usd']:.4f} | {token['percent_change_24h']}% 24h\n"
    return result
