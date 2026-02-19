import json
import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable, Union
from functools import wraps
import logging
from dataclasses import dataclass, asdict

try:
    import redis
    import aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)

# Cache configuration
@dataclass
class CacheConfig:
    default_ttl: int = 300  # 5 minutes
    token_info_ttl: int = 180  # 3 minutes (more frequent updates)
    whale_activity_ttl: int = 60  # 1 minute (very dynamic)
    wallet_info_ttl: int = 600  # 10 minutes (less frequent)
    sentiment_ttl: int = 120  # 2 minutes (social data changes quickly)
    analysis_ttl: int = 900  # 15 minutes (computed analysis can be cached longer)
    max_retries: int = 3
    retry_delay: float = 0.1

class CacheManager:
    """Multi-layer cache manager with Redis and in-memory fallback"""
    
    def __init__(self, redis_url: Optional[str] = None, config: CacheConfig = None):
        self.config = config or CacheConfig()
        self.redis_client = None
        self.memory_cache = {}  # Fallback in-memory cache
        self.cache_stats = {"hits": 0, "misses": 0, "errors": 0}
        
        if REDIS_AVAILABLE and redis_url:
            try:
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
                self.redis_client.ping()  # Test connection
                logger.info("Redis cache initialized successfully")
            except Exception as e:
                logger.warning(f"Redis connection failed, using memory cache: {e}")
        else:
            logger.info("Using in-memory cache (Redis not available)")
    
    def _generate_cache_key(self, prefix: str, *args, **kwargs) -> str:
        """Generate consistent cache keys"""
        key_data = f"{prefix}:{str(args)}:{str(sorted(kwargs.items()))}"
        return hashlib.md5(key_data.encode()).hexdigest()[:16]
    
    def _serialize_data(self, data: Any) -> str:
        """Serialize data for caching"""
        if isinstance(data, (dict, list)):
            return json.dumps(data, default=str)
        return str(data)
    
    def _deserialize_data(self, data: str) -> Any:
        """Deserialize cached data"""
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return data
    
    async def get(self, key: str) -> Optional[Any]:
        """Get data from cache"""
        try:
            # Try Redis first
            if self.redis_client:
                cached = self.redis_client.get(key)
                if cached:
                    self.cache_stats["hits"] += 1
                    return self._deserialize_data(cached)
            
            # Fallback to memory cache
            if key in self.memory_cache:
                item = self.memory_cache[key]
                if datetime.now() < item["expires"]:
                    self.cache_stats["hits"] += 1
                    return item["data"]
                else:
                    del self.memory_cache[key]
            
            self.cache_stats["misses"] += 1
            return None
            
        except Exception as e:
            logger.error(f"Cache get error for key {key}: {e}")
            self.cache_stats["errors"] += 1
            return None
    
    async def set(self, key: str, data: Any, ttl: int = None) -> bool:
        """Set data in cache"""
        try:
            ttl = ttl or self.config.default_ttl
            serialized = self._serialize_data(data)
            
            # Try Redis first
            if self.redis_client:
                self.redis_client.setex(key, ttl, serialized)
            
            # Always set in memory cache as backup
            self.memory_cache[key] = {
                "data": data,
                "expires": datetime.now() + timedelta(seconds=ttl)
            }
            
            return True
            
        except Exception as e:
            logger.error(f"Cache set error for key {key}: {e}")
            self.cache_stats["errors"] += 1
            return False
    
    def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate keys matching pattern"""
        count = 0
        try:
            if self.redis_client:
                keys = self.redis_client.keys(f"*{pattern}*")
                if keys:
                    count += self.redis_client.delete(*keys)
            
            # Clean memory cache
            keys_to_remove = [k for k in self.memory_cache.keys() if pattern in k]
            for key in keys_to_remove:
                del self.memory_cache[key]
                count += 1
                
        except Exception as e:
            logger.error(f"Cache invalidation error for pattern {pattern}: {e}")
        
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_requests = self.cache_stats["hits"] + self.cache_stats["misses"]
        hit_rate = (self.cache_stats["hits"] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            **self.cache_stats,
            "hit_rate_percent": round(hit_rate, 2),
            "memory_cache_size": len(self.memory_cache),
            "redis_available": self.redis_client is not None
        }

# Global cache manager instance
cache_manager = CacheManager()

def cache_with_strategy(cache_type: str = "default", ttl: int = None, 
                       invalidate_on_error: bool = False):
    """
    Advanced caching decorator with multiple strategies
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Determine TTL based on cache type
            ttl_map = {
                "token_info": cache_manager.config.token_info_ttl,
                "whale_activity": cache_manager.config.whale_activity_ttl,
                "wallet_info": cache_manager.config.wallet_info_ttl,
                "sentiment": cache_manager.config.sentiment_ttl,
                "analysis": cache_manager.config.analysis_ttl,
                "default": cache_manager.config.default_ttl
            }
            
            cache_ttl = ttl or ttl_map.get(cache_type, cache_manager.config.default_ttl)
            cache_key = cache_manager._generate_cache_key(f"{func.__name__}_{cache_type}", *args, **kwargs)
            
            # Try to get from cache
            cached_result = await cache_manager.get(cache_key)
            if cached_result is not None:
                logger.debug(f"Cache hit for {func.__name__}")
                return cached_result
            
            # Execute function with retries
            for attempt in range(cache_manager.config.max_retries):
                try:
                    result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
                    
                    # Cache successful results
                    await cache_manager.set(cache_key, result, cache_ttl)
                    logger.debug(f"Cached result for {func.__name__}")
                    return result
                    
                except Exception as e:
                    logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}")
                    
                    if attempt < cache_manager.config.max_retries - 1:
                        await asyncio.sleep(cache_manager.config.retry_delay * (2 ** attempt))
                    else:
                        if invalidate_on_error:
                            cache_manager.invalidate_pattern(func.__name__)
                        raise e
            
            return None
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Convert to async for consistent handling
            if asyncio.iscoroutinefunction(func):
                return asyncio.create_task(async_wrapper(*args, **kwargs))
            else:
                return asyncio.run(async_wrapper(*args, **kwargs))
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator

# Enhanced analysis functions with caching
@cache_with_strategy(cache_type="analysis", ttl=900)  # 15 minutes
async def analyze_token_ai_cached(contract_address: str) -> Dict[str, Any]:
    """Cached version of token AI analysis"""
    from . import analyze_token_ai  # Import from your existing module
    return analyze_token_ai(contract_address)

@cache_with_strategy(cache_type="analysis", ttl=900)
async def analyze_wallet_ai_cached(wallet_address: str) -> Dict[str, Any]:
    """Cached version of wallet AI analysis"""
    from . import analyze_wallet_ai  # Import from your existing module
    return analyze_wallet_ai(wallet_address)

@cache_with_strategy(cache_type="token_info", ttl=180)
async def get_token_info_cached(contract_address: str) -> Dict[str, Any]:
    """Cached token information retrieval"""
    try:
        from services.tonviewer_api import get_token_info_from_tonviewer
        return get_token_info_from_tonviewer(contract_address)
    except Exception as e:
        logger.error(f"Token info fetch error: {e}")
        return {}

@cache_with_strategy(cache_type="whale_activity", ttl=60, invalidate_on_error=True)
async def get_whale_activity_cached(contract_address: str) -> List[Dict]:
    """Cached whale activity data"""
    try:
        from services.whale_watcher import extract_whale_activity
        return extract_whale_activity(contract_address)
    except Exception as e:
        logger.error(f"Whale activity fetch error: {e}")
        return []

@cache_with_strategy(cache_type="sentiment", ttl=120)
async def get_sentiment_data_cached(token_symbol: str) -> Dict[str, Any]:
    """Cached sentiment analysis data"""
    try:
        # Your sentiment data fetching logic here
        # This is a placeholder - replace with actual implementation
        tweet_data = []  # fetch_tweet_data(token_symbol)
        from . import process_sentiment_data
        return process_sentiment_data(tweet_data)
    except Exception as e:
        logger.error(f"Sentiment data fetch error: {e}")
        return process_sentiment_data([])

@cache_with_strategy(cache_type="wallet_info", ttl=600)
async def get_wallet_info_cached(wallet_address: str) -> Dict[str, Any]:
    """Cached wallet information"""
    try:
        from services.tonapi import get_wallet_info
        return get_wallet_info(wallet_address)
    except Exception as e:
        logger.error(f"Wallet info fetch error: {e}")
        return {}

class CachePrewarmer:
    """Preemptively warm cache for popular tokens/wallets"""
    
    def __init__(self, cache_manager: CacheManager):
        self.cache_manager = cache_manager
        self.popular_tokens = []  # Load from config or database
        self.popular_wallets = []
    
    async def prewarm_popular_data(self):
        """Prewarm cache with popular token/wallet data"""
        tasks = []
        
        # Prewarm popular tokens
        for token in self.popular_tokens[:10]:  # Limit to avoid overwhelming APIs
            tasks.append(get_token_info_cached(token))
            tasks.append(get_whale_activity_cached(token))
        
        # Prewarm popular wallets
        for wallet in self.popular_wallets[:5]:
            tasks.append(get_wallet_info_cached(wallet))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            logger.info(f"Prewarmed {len([r for r in results if not isinstance(r, Exception)])} cache entries")

# Cache monitoring and cleanup
class CacheMonitor:
    """Monitor cache performance and cleanup"""
    
    @staticmethod
    def cleanup_expired_memory_cache():
        """Clean expired entries from memory cache"""
        current_time = datetime.now()
        expired_keys = [
            key for key, value in cache_manager.memory_cache.items()
            if current_time >= value["expires"]
        ]
        
        for key in expired_keys:
            del cache_manager.memory_cache[key]
        
        logger.info(f"Cleaned {len(expired_keys)} expired cache entries")
        return len(expired_keys)
    
    @staticmethod
    def get_cache_health() -> Dict[str, Any]:
        """Get comprehensive cache health metrics"""
        stats = cache_manager.get_stats()
        
        return {
            **stats,
            "memory_usage_mb": len(str(cache_manager.memory_cache).encode()) / (1024 * 1024),
            "health_status": "good" if stats["hit_rate_percent"] > 60 else "needs_attention",
            "recommendations": CacheMonitor._get_recommendations(stats)
        }
    
    @staticmethod
    def _get_recommendations(stats: Dict) -> List[str]:
        """Generate cache optimization recommendations"""
        recommendations = []
        
        if stats["hit_rate_percent"] < 50:
            recommendations.append("Consider increasing TTL values")
        
        if stats["errors"] > stats["hits"] * 0.1:
            recommendations.append("High error rate - check Redis connectivity")
        
        if stats["memory_cache_size"] > 1000:
            recommendations.append("Memory cache growing large - consider cleanup")
        
        return recommendations

# Usage example and initialization
def initialize_enhanced_caching(redis_url: str = None, config: CacheConfig = None):
    """Initialize the enhanced caching system"""
    global cache_manager
    cache_manager = CacheManager(redis_url, config)
    
    # Start background cleanup task
    async def cleanup_task():
        while True:
            await asyncio.sleep(300)  # Clean every 5 minutes
            CacheMonitor.cleanup_expired_memory_cache()
    
    # Start prewarming task
    prewarmer = CachePrewarmer(cache_manager)
    
    asyncio.create_task(cleanup_task())
    asyncio.create_task(prewarmer.prewarm_popular_data())
    
    logger.info("Enhanced caching system initialized")
    return cache_manager