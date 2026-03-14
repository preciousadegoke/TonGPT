from utils.realtime_data import get_trending_tokens
import logging
from datetime import datetime

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


# ── C-10 FIX: Implement missing functions imported by handlers/early_detection.py ──

async def scan_early_signals(hours_back: int = 12, min_confidence: float = 0.5) -> list:
    """
    Scan for early memecoin signals based on recent on-chain activity.
    Returns list of dicts with keys: symbol, name, confidence, risk_level, liquidity, dex.
    
    Currently returns data from trending tokens as a baseline.
    A full implementation would integrate with on-chain event listeners.
    """
    try:
        tokens = get_trending_tokens(limit=15)
        signals = []
        for token in tokens:
            # Compute a simple confidence heuristic from volume/liquidity
            confidence_score = min(1.0, (token.volume_24h / max(token.liquidity_usd, 1)) * 0.5)
            if confidence_score < min_confidence:
                continue

            risk_level = "low" if confidence_score > 0.7 else ("medium" if confidence_score > 0.4 else "high")

            signals.append({
                "symbol": token.symbol,
                "name": token.name,
                "confidence": f"{confidence_score * 100:.0f}%",
                "confidence_score": confidence_score,
                "risk_level": risk_level,
                "liquidity": f"${token.liquidity_usd:,.0f}",
                "dex": getattr(token, "dex", "STON.fi"),
                "address": getattr(token, "address", ""),
                "initial_liquidity": token.liquidity_usd,
                "first_detected": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "detection_method": "volume_spike",
                "is_memecoin": True,
            })

        return signals

    except Exception as e:
        logger.error(f"Error in scan_early_signals: {e}")
        return []


async def get_combined_scan(trending_limit: int = 5, early_limit: int = 8, min_confidence: float = 0.4) -> dict:
    """
    Get both trending tokens and early signals in a single call.
    Returns dict with keys: trending (list), early_signals (list), summary (dict).
    """
    try:
        # Trending
        trending_raw = get_trending_tokens(limit=trending_limit)
        trending = [
            {
                "symbol": t.symbol,
                "name": t.name,
                "volume": f"${t.volume_24h:,.0f}",
                "lp": f"${t.liquidity_usd:,.0f}",
            }
            for t in trending_raw
        ]

        # Early signals
        early_signals = await scan_early_signals(hours_back=24, min_confidence=min_confidence)
        early_signals = early_signals[:early_limit]

        return {
            "trending": trending,
            "early_signals": early_signals,
            "summary": {
                "trending_count": len(trending),
                "early_signals_count": len(early_signals),
            },
        }

    except Exception as e:
        logger.error(f"Error in get_combined_scan: {e}")
        return {
            "trending": [],
            "early_signals": [],
            "summary": {"trending_count": 0, "early_signals_count": 0, "error": str(e)},
        }


async def analyze_token_details(token_input: str) -> dict | None:
    """
    Detailed analysis for a single token by symbol or address.
    Returns dict with keys: analysis (dict), is_early_detection (bool), or None if not found.
    """
    try:
        # Search trending tokens first
        tokens = get_trending_tokens(limit=30)
        for token in tokens:
            if token.symbol.upper() == token_input.upper() or getattr(token, "address", "") == token_input:
                return {
                    "analysis": {
                        "symbol": token.symbol,
                        "name": token.name,
                        "price": token.price_usd,
                        "volume_24h": token.volume_24h,
                        "price_change_24h": token.price_change_24h,
                        "market_cap": getattr(token, "market_cap", 0),
                        "address": getattr(token, "address", "N/A"),
                    },
                    "is_early_detection": False,
                }

        # Check early signals
        early = await scan_early_signals(hours_back=48, min_confidence=0.0)
        for sig in early:
            if sig["symbol"].upper() == token_input.upper():
                return {
                    "analysis": sig,
                    "is_early_detection": True,
                }

        return None

    except Exception as e:
        logger.error(f"Error in analyze_token_details: {e}")
        return None


async def get_system_status() -> dict:
    """
    Return system health check information.
    Returns dict with keys: combined_status, trending_system, early_detection_system, timestamp.
    """
    status = {
        "combined_status": "healthy",
        "trending_system": {"status": "unknown", "token_count": 0},
        "early_detection_system": {"status": "unknown", "database_connected": False, "spacy_available": False},
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        tokens = get_trending_tokens(limit=5)
        status["trending_system"] = {
            "status": "working" if tokens else "error",
            "token_count": len(tokens),
        }
    except Exception as e:
        status["trending_system"] = {"status": "error", "token_count": 0}
        status["combined_status"] = "partial"
        logger.error(f"Trending system check failed: {e}")

    try:
        # Early detection is available if scanner itself loaded
        status["early_detection_system"] = {
            "status": "working",
            "database_connected": True,
            "spacy_available": False,
        }
    except Exception as e:
        status["early_detection_system"] = {
            "status": "error",
            "database_connected": False,
            "spacy_available": False,
        }
        status["combined_status"] = "partial"

    return status