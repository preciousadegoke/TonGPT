"""
Analysis services for TonGPT - Token and wallet analysis functionality
Enhanced with multi-layer caching system
"""
import json
import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
from functools import wraps
import logging

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

from services.analysis_cache import cache_manager

logger = logging.getLogger(__name__)


def cache_result(cache_type: str = "default", ttl: Optional[int] = None):
    """Caching decorator for analysis functions (supports sync and async targets)."""
    def decorator(func: Callable) -> Callable:
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                cache_mgr = cache_manager
                cache_ttl = ttl or cache_mgr.config.default_ttl
                cache_key = cache_mgr._generate_cache_key(f"{func.__name__}_{cache_type}", *args, **kwargs)
                cached = await cache_mgr.get(cache_key)
                if cached is not None:
                    logger.debug(f"[cache_result] HIT (async) for {func.__name__}")
                    return cached
                result = await func(*args, **kwargs)
                await cache_mgr.set(cache_key, result, cache_ttl)
                logger.debug(f"[cache_result] MISS -> cached (async) for {func.__name__}")
                return result
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                # Use memory_cache directly (sync-safe) since CacheManager.get/set are async
                cache_mgr = cache_manager
                cache_ttl = ttl or cache_mgr.config.default_ttl
                cache_key = cache_mgr._generate_cache_key(f"{func.__name__}_{cache_type}", *args, **kwargs)
                # Check memory cache
                item = cache_mgr.memory_cache.get(cache_key)
                if item and datetime.now() < item["expires"]:
                    logger.debug(f"[cache_result] HIT (sync) for {func.__name__}")
                    cache_mgr.cache_stats["hits"] += 1
                    return item["data"]
                cache_mgr.cache_stats["misses"] += 1
                result = func(*args, **kwargs)
                # Store in memory cache
                cache_mgr.memory_cache[cache_key] = {
                    "data": result,
                    "expires": datetime.now() + timedelta(seconds=cache_ttl)
                }
                logger.debug(f"[cache_result] MISS -> cached (sync) for {func.__name__}")
                return result
            return sync_wrapper
    return decorator


# Enhanced analysis functions with caching
@cache_result(cache_type="analysis", ttl=900)
def calculate_risk_score(token_info: Dict, whale_transactions: List) -> int:
    """Calculate risk score for a token (cached for 15 minutes)"""
    score = 50  # Start with neutral score
    
    # Adjust based on holders
    holders = token_info.get('holders_count', 0)
    if isinstance(holders, str):
        try:
            holders = int(holders.replace(',', ''))
        except:
            holders = 0
    
    if holders > 10000:
        score -= 20
    elif holders > 1000:
        score -= 10
    elif holders < 100:
        score += 30
    
    # Adjust based on whale activity
    if len(whale_transactions) > 5:
        score += 15
    elif len(whale_transactions) > 2:
        score += 5
    
    # Adjust based on verification
    if token_info.get('verified') or 'verified' in str(token_info.get('name', '')).lower():
        score -= 15
    
    return max(0, min(100, score))

@cache_result(cache_type="sentiment", ttl=120)
def process_sentiment_data(tweet_data: List[Dict]) -> Dict:
    """Process tweet sentiment data (cached for 2 minutes)"""
    if not tweet_data:
        return {
            "overall_sentiment": "neutral",
            "bullish_percentage": 33,
            "bearish_percentage": 33,
            "neutral_percentage": 34,
            "confidence": "low"
        }
    
    bullish_count = sum(1 for post in tweet_data if post.get('sentiment') == 'bullish')
    bearish_count = sum(1 for post in tweet_data if post.get('sentiment') == 'bearish')
    neutral_count = len(tweet_data) - bullish_count - bearish_count
    
    total = len(tweet_data)
    if total == 0:
        return {
            "overall_sentiment": "neutral",
            "bullish_percentage": 33.0,
            "bearish_percentage": 33.0,
            "neutral_percentage": 34.0,
            "confidence": "low",
        }
    
    bullish_pct = (bullish_count / total) * 100
    bearish_pct = (bearish_count / total) * 100
    neutral_pct = (neutral_count / total) * 100
    
    # Determine overall sentiment
    if bullish_pct > 50:
        overall = "bullish"
    elif bearish_pct > 50:
        overall = "bearish"
    else:
        overall = "neutral"
    
    return {
        "overall_sentiment": overall,
        "bullish_percentage": round(bullish_pct, 1),
        "bearish_percentage": round(bearish_pct, 1),
        "neutral_percentage": round(neutral_pct, 1),
        "confidence": "high" if total > 20 else "medium" if total > 10 else "low"
    }

# Cached helper functions for external API calls
@cache_result(cache_type="token_info", ttl=180)
def get_token_info_cached(contract_address: str) -> Dict:
    """Cached token info retrieval (cached for 3 minutes)"""
    try:
        from services.tonviewer_api import get_token_info_from_tonviewer
        return get_token_info_from_tonviewer(contract_address)
    except Exception as e:
        logger.error(f"Token info fetch error: {e}")
        return {}

@cache_result(cache_type="whale_activity", ttl=60)
def get_whale_activity_cached(contract_address: str) -> List:
    """Cached whale activity retrieval (cached for 1 minute)"""
    try:
        from services.whale_watcher import extract_whale_activity
        return extract_whale_activity(contract_address)
    except Exception as e:
        logger.error(f"Whale activity fetch error: {e}")
        return []

@cache_result(cache_type="wallet_info", ttl=600)
def get_wallet_info_cached(wallet_address: str) -> Dict:
    """Cached wallet info retrieval (cached for 10 minutes)"""
    try:
        from services.tonapi import get_wallet_info
        return get_wallet_info(wallet_address)
    except Exception as e:
        logger.error(f"Wallet info fetch error: {e}")
        return {}

@cache_result(cache_type="wallet_info", ttl=600)
def get_transactions_cached(wallet_address: str, limit: int = 50) -> Dict:
    """Cached transactions retrieval (cached for 10 minutes)"""
    try:
        from services.tonapi import get_transactions
        return get_transactions(wallet_address, limit=limit)
    except Exception as e:
        logger.error(f"Transactions fetch error: {e}")
        return {}

@cache_result(cache_type="analysis", ttl=900)
def analyze_token_ai(contract_address: str) -> Dict[str, Any]:
    """AI analysis for tokens (cached for 15 minutes)"""
    try:
        # Get token info using cached version
        token_info = get_token_info_cached(contract_address)
        
        # Get whale transactions using cached version
        whale_txs = get_whale_activity_cached(contract_address)
        
        # Generate analysis
        analysis = {
            "contract_address": contract_address,
            "analysis_type": "token",
            "risk_assessment": {
                "level": "medium",
                "score": calculate_risk_score(token_info or {}, whale_txs),
                "factors": []
            },
            "predictions": {
                "short_term": "neutral",
                "confidence": 0.65
            },
            "recommendations": [],
            "analyzed_at": datetime.now().isoformat()
        }
        
        # Add risk factors
        if len(whale_txs) > 3:
            analysis["risk_assessment"]["factors"].append("High whale activity detected")
        
        if not token_info:
            analysis["risk_assessment"]["factors"].append("Limited token information available")
            analysis["recommendations"].append("Verify token contract manually")
        
        # Update risk level based on score
        score = analysis["risk_assessment"]["score"]
        if score >= 70:
            analysis["risk_assessment"]["level"] = "high"
        elif score >= 40:
            analysis["risk_assessment"]["level"] = "medium"
        else:
            analysis["risk_assessment"]["level"] = "low"
        
        return analysis
        
    except Exception as e:
        logger.error(f"Token analysis error for {contract_address}: {e}")
        return {
            "error": str(e),
            "analysis_type": "token",
            "contract_address": contract_address,
            "analyzed_at": datetime.now().isoformat()
        }

@cache_result(cache_type="analysis", ttl=900)
def analyze_wallet_ai(wallet_address: str) -> Dict[str, Any]:
    """AI analysis for wallets (cached for 15 minutes)"""
    try:
        # Get wallet info using cached version
        wallet_info = get_wallet_info_cached(wallet_address)
        
        # Get transactions using cached version
        transactions = get_transactions_cached(wallet_address, limit=50)
        
        balance_ton = wallet_info.get('balance_ton', 0)
        whale_category = wallet_info.get('whale_category', 'regular')
        
        analysis = {
            "wallet_address": wallet_address,
            "analysis_type": "wallet",
            "wallet_profile": {
                "category": whale_category,
                "balance_ton": balance_ton,
                "activity_level": "high" if len(transactions.get('transactions', [])) > 20 else "medium" if len(transactions.get('transactions', [])) > 5 else "low"
            },
            "behavior_analysis": {
                "trading_pattern": "active" if balance_ton > 1000 else "holder",
                "risk_level": "high" if whale_category in ['large_whale', 'mega_whale'] else "medium"
            },
            "insights": [],
            "analyzed_at": datetime.now().isoformat()
        }
        
        # Add insights
        if whale_category != 'regular':
            analysis["insights"].append(f"This is a {whale_category.replace('_', ' ')} wallet")
        
        if balance_ton > 100000:
            analysis["insights"].append("Extremely large TON holdings detected")
        
        # Add transaction pattern insights
        tx_count = len(transactions.get('transactions', []))
        if tx_count > 50:
            analysis["insights"].append("High transaction frequency detected")
        elif tx_count < 5:
            analysis["insights"].append("Low activity wallet")
        
        return analysis
        
    except Exception as e:
        logger.error(f"Wallet analysis error for {wallet_address}: {e}")
        return {
            "error": str(e),
            "analysis_type": "wallet",
            "wallet_address": wallet_address,
            "analyzed_at": datetime.now().isoformat()
        }

def is_memecoin_only(token: Dict) -> bool:
    """Strict memecoin filtering - excludes major cryptocurrencies (cached implicitly via token analysis)"""
    try:
        name = token.get('name', '').lower()
        symbol = token.get('symbol', '').lower()
        
        # EXCLUDE major cryptocurrencies first
        major_cryptos = [
            'toncoin', 'ton', 'bitcoin', 'ethereum', 'bnb', 'usdt', 'usdc', 'busd',
            'cardano', 'solana', 'polygon', 'avalanche', 'chainlink', 'uniswap',
            'litecoin', 'stellar', 'dogecoin', 'shiba inu', 'matic', 'ftx token',
            'cosmos', 'algorand', 'vechain', 'filecoin', 'tron', 'ethereum classic',
            'monero', 'eos', 'aave', 'compound', 'maker', 'yearn.finance', 'sushi',
            'pancakeswap', '1inch', 'curve', 'balancer', 'notcoin'
        ]
        
        # Exclude if it's a major crypto
        if name in major_cryptos or symbol in ['ton', 'not', 'btc', 'eth', 'bnb', 'usdt', 'usdc', 'busd', 'ada', 'sol', 'matic', 'avax', 'link', 'uni', 'ltc', 'xlm', 'doge', 'shib', 'trx', 'etc', 'xmr', 'eos']:
            return False
        
        # EXCLUDE utility/DeFi tokens
        utility_keywords = [
            'swap', 'dex', 'pool', 'vault', 'stake', 'farm', 'bridge', 'protocol', 
            'dao', 'defi', 'yield', 'liquidity', 'finance', 'trading', 'exchange',
            'lending', 'staking', 'governance', 'oracle', 'chain', 'network',
            'platform', 'infrastructure', 'metaverse', 'nft', 'gaming'
        ]
        
        # Exclude utility tokens
        if any(keyword in name or keyword in symbol for keyword in utility_keywords):
            return False
        
        # INCLUDE only memecoin keywords
        memecoin_keywords = [
            'dog', 'cat', 'puppy', 'kitten', 'pup', 'meme', 'pepe', 'wojak', 'chad',
            'inu', 'shib', 'floki', 'baby', 'moon', 'rocket', 'diamond', 'ape', 
            'frog', 'hamster', 'pig', 'bear', 'bull', 'lion', 'tiger', 'wolf', 
            'fox', 'rabbit', 'bonk', 'safe', 'gem', 'pump', 'lambo', 'hodl', 
            'yolo', 'based', 'degen', 'gigachad', 'cheems', 'doge',
            'shibainu', 'flokiinu', 'babydog', 'safemoon', 'elonmusk', 'tesla',
            'memecoin', 'memetoken', 'shibu', 'doggo', 'pupper', 'cate', 'kitteh'
        ]
        
        # Must contain memecoin keywords
        is_memecoin = any(keyword in name or keyword in symbol for keyword in memecoin_keywords)
        
        return is_memecoin
    except Exception as e:
        logger.error(f"Memecoin filtering error: {e}")
        return False

# Cache management utilities
def get_cache_stats() -> Dict[str, Any]:
    """Get cache performance statistics"""
    return cache_manager.get_stats()

def clear_cache_pattern(pattern: str = None) -> int:
    """Clear cache entries matching pattern or all if no pattern"""
    cache_mgr = cache_manager
    
    if pattern:
        # Clear memory cache entries matching pattern
        keys_to_remove = [k for k in cache_mgr.memory_cache.keys() if pattern in k]
        for key in keys_to_remove:
            del cache_mgr.memory_cache[key]
        
        # Clear Redis cache if available
        if cache_mgr.redis_client:
            redis_keys = cache_mgr.redis_client.keys(f"*{pattern}*")
            if redis_keys:
                cache_mgr.redis_client.delete(*redis_keys)
        
        return len(keys_to_remove)
    else:
        # Clear all caches
        memory_count = len(cache_mgr.memory_cache)
        cache_mgr.memory_cache.clear()
        
        if cache_mgr.redis_client:
            cache_mgr.redis_client.flushdb()
        
        return memory_count

def cleanup_expired_cache():
    """Clean up expired cache entries"""
    cache_mgr = cache_manager
    current_time = datetime.now()
    
    expired_keys = [
        key for key, value in cache_mgr.memory_cache.items()
        if current_time >= value["expires"]
    ]
    
    for key in expired_keys:
        del cache_mgr.memory_cache[key]
    
    logger.info(f"Cleaned {len(expired_keys)} expired cache entries")
    return len(expired_keys)

# Background cache maintenance (call this in your main app startup)
def start_cache_maintenance():
    """Start background cache maintenance tasks"""
    import threading
    import time
    
    def maintenance_worker():
        while True:
            try:
                cleanup_expired_cache()
                time.sleep(300)  # Clean every 5 minutes
            except Exception as e:
                logger.error(f"Cache maintenance error: {e}")
                time.sleep(60)  # Retry in 1 minute on error
    
    thread = threading.Thread(target=maintenance_worker, daemon=True)
    thread.start()
    logger.info("Cache maintenance thread started")