from utils.realtime_data import get_trending_tokens
import logging

logger = logging.getLogger(__name__)

def scan_memecoins(limit=10):  # Added limit parameter with default value
    """
    Legacy function for scanning memecoins
    Redirects to new realtime_data system
    """
    try:
        # Get TokenData objects (which are dataclasses)
        tokens = get_trending_tokens(limit=limit or 15)
        
        # Format for legacy compatibility
        formatted_coins = []
        for token in tokens:
            coin = {
                'name': token.name,
                'symbol': token.symbol,
                'lp': f"${token.liquidity_usd:,.0f}",
                'volume': f"${token.volume_24h:,.0f}",
                'hype': 'High' if token.volume_24h > 50000 else 'Medium',
                'link': f"STON.fi - {token.symbol}"
            }
            formatted_coins.append(coin)
        
        return formatted_coins
        
    except Exception as e:
        logger.error(f"Error in scan_memecoins: {e}")
        return []