from datetime import datetime
import math


def shorten_address(address: str, length: int = 6) -> str:
    """
    Shortens a crypto address for UI display.
    E.g. "EQB...XYZ"
    """
    if not address or len(address) < length * 2:
        return address
    return f"{address[:length]}...{address[-length:]}"


def format_token_amount(amount: float, decimals: int = 2) -> str:
    """
    Formats token values with fixed decimal places and commas.
    """
    try:
        return f"{amount:,.{decimals}f}"
    except:
        return str(amount)


def time_ago(timestamp: int) -> str:
    """
    Converts a UNIX timestamp into "X mins/hours ago".
    """
    now = datetime.utcnow()
    dt = datetime.utcfromtimestamp(timestamp)
    diff = now - dt

    seconds = diff.total_seconds()
    if seconds < 60:
        return "Just now"
    elif seconds < 3600:
        return f"{int(seconds / 60)} min(s) ago"
    elif seconds < 86400:
        return f"{int(seconds / 3600)} hr(s) ago"
    else:
        return f"{int(seconds / 86400)} day(s) ago"


def emoji_change(percent: float) -> str:
    """
    Returns an emoji based on percent change.
    """
    if percent > 0:
        return "🟢📈"
    elif percent < 0:
        return "🔴📉"
    else:
        return "⚪️⏸️"


def get_tier_by_paid_amount(amount: float) -> str:
    """
    Classifies user by total TON paid.
    """
    if amount >= 18:
        return "💎 Lifetime"
    elif amount >= 10:
        return "👑 Elite"
    elif amount >= 6:
        return "🥇 Pro+"
    elif amount >= 3:
        return "🥈 Pro"
    elif amount >= 0.8:
        return "🥉 Starter"
    return "🚫 Free"


def sanitize_username(username: str) -> str:
    """
    Ensures a username string is safe and displayable.
    """
    return username.replace("@", "") if username else "Anonymous"


def chunk_list(items: list, size: int) -> list:
    """
    Breaks a list into chunks of specified size.
    Useful for paginated button layouts.
    """
    return [items[i:i + size] for i in range(0, len(items), size)]
