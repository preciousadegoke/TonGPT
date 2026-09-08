import os
import redis
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def create_redis_client() -> Optional[redis.Redis]:
    """Create Redis client with support for different configuration formats"""
    
    # Try REDIS_URL first (if provided)
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        try:
            client = redis.from_url(redis_url, decode_responses=True)
            client.ping()  # Test connection
            logger.info("✅ Redis connected via REDIS_URL")
            return client
        except Exception as e:
            logger.error(f"❌ Redis URL connection failed: {e}")
    
    # Try host/port configuration (your setup)
    redis_host = os.getenv("REDIS_HOST")
    redis_port = os.getenv("REDIS_PORT")
    redis_password = os.getenv("REDIS_PASSWORD")
    
    if redis_host and redis_port:
        try:
            client = redis.Redis(
                host=redis_host,
                port=int(redis_port),
                password=redis_password,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                health_check_interval=30
            )
            client.ping()  # Test connection
            logger.info(f"✅ Redis connected to {redis_host}:{redis_port}")
            return client
        except Exception as e:
            logger.error(f"❌ Redis host/port connection failed: {e}")
    
    # Fallback to localhost (for development)
    try:
        client = redis.Redis(
            host='localhost',
            port=6379,
            decode_responses=True,
            socket_connect_timeout=2
        )
        client.ping()
        logger.warning("⚠️ Using localhost Redis (development mode)")
        return client
    except Exception as e:
        logger.error(f"❌ Local Redis connection failed: {e}")
    
    logger.critical("❌ No Redis connection available")
    return None

# Create the global Redis client
redis_client = create_redis_client()

# Provide a safe Redis interface for when Redis is unavailable
class SafeRedisClient:
    """Safe Redis client that handles connection failures gracefully"""
    
    def __init__(self, client: Optional[redis.Redis]):
        self.client = client
        self.available = client is not None
    
    def ping(self):
        if self.client:
            return self.client.ping()
        return False
    
    def get(self, key: str):
        if self.client:
            try:
                return self.client.get(key)
            except Exception as e:
                logger.error(f"Redis GET error: {e}")
        return None
    
    def set(self, key: str, value, ex: int = None, nx: bool = False):
        """SET with optional expiry and NX (set-if-not-exists).

        With nx=True the return value distinguishes 'won the race' (truthy)
        from 'key already existed' (None) — used for atomic cooldowns/dedup.
        """
        if self.client:
            try:
                return self.client.set(key, value, ex=ex, nx=nx)
            except Exception as e:
                logger.error(f"Redis SET error: {e}")
        return False
    
    def delete(self, *keys):
        if self.client:
            try:
                return self.client.delete(*keys)
            except Exception as e:
                logger.error(f"Redis DELETE error: {e}")
        return 0
    
    def incr(self, key: str):
        if self.client:
            try:
                return self.client.incr(key)
            except Exception as e:
                logger.error(f"Redis INCR error: {e}")
        return 0

    def incrby(self, key: str, amount: int) -> int:
        if self.client:
            try:
                return self.client.incrby(key, amount)
            except Exception as e:
                logger.error(f"Redis INCRBY error: {e}")
        return 0

    def decrby(self, key: str, amount: int) -> int:
        if self.client:
            try:
                return self.client.decrby(key, amount)
            except Exception as e:
                logger.error(f"Redis DECRBY error: {e}")
        return 0
    
    def incrbyfloat(self, key: str, amount: float):
        if self.client:
            try:
                return self.client.incrbyfloat(key, amount)
            except Exception as e:
                logger.error(f"Redis INCRBYFLOAT error: {e}")
        return 0
    
    def ttl(self, key: str):
        if self.client:
            try:
                return self.client.ttl(key)
            except Exception as e:
                logger.error(f"Redis TTL error: {e}")
        return -1
    
    def expire(self, key: str, seconds: int):
        if self.client:
            try:
                return self.client.expire(key, seconds)
            except Exception as e:
                logger.error(f"Redis EXPIRE error: {e}")
        return False
    
    def exists(self, *keys):
        if self.client:
            try:
                return self.client.exists(*keys)
            except Exception as e:
                logger.error(f"Redis EXISTS error: {e}")
        return 0
    
    def smembers(self, key: str):
        if self.client:
            try:
                return self.client.smembers(key)
            except Exception as e:
                logger.error(f"Redis SMEMBERS error: {e}")
        return set()
    
    def sadd(self, key: str, *members):
        if self.client:
            try:
                return self.client.sadd(key, *members)
            except Exception as e:
                logger.error(f"Redis SADD error: {e}")
        return 0
    
    def srem(self, key: str, *members):
        if self.client:
            try:
                return self.client.srem(key, *members)
            except Exception as e:
                logger.error(f"Redis SREM error: {e}")
        return 0
    
    def zadd(self, key: str, mapping: dict):
        if self.client:
            try:
                return self.client.zadd(key, mapping)
            except Exception as e:
                logger.error(f"Redis ZADD error: {e}")
        return 0
    
    def zrange(self, key: str, start: int, end: int, withscores: bool = False):
        if self.client:
            try:
                return self.client.zrange(key, start, end, withscores=withscores)
            except Exception as e:
                logger.error(f"Redis ZRANGE error: {e}")
        return []
    
    def hget(self, key: str, field: str):
        if self.client:
            try:
                return self.client.hget(key, field)
            except Exception as e:
                logger.error(f"Redis HGET error: {e}")
        return None
    
    def hset(self, key: str, field: str, value):
        if self.client:
            try:
                return self.client.hset(key, field, value)
            except Exception as e:
                logger.error(f"Redis HSET error: {e}")
        return 0
    
    def hexists(self, key: str, field: str):
        if self.client:
            try:
                return self.client.hexists(key, field)
            except Exception as e:
                logger.error(f"Redis HEXISTS error: {e}")
        return False
    
    def scan_iter(self, match: str = None, count: int = 100):
        """Incrementally iterate over keys matching a pattern (avoids blocking O(n) KEYS)."""
        if self.client:
            try:
                return self.client.scan_iter(match=match, count=count)
            except Exception as e:
                logger.error(f"Redis SCAN_ITER error: {e}")
        return iter([])

    def hgetall(self, key: str):
        if self.client:
            try:
                return self.client.hgetall(key)
            except Exception as e:
                logger.error(f"Redis HGETALL error: {e}")
        return {}

    def hdel(self, key: str, *fields):
        if self.client:
            try:
                return self.client.hdel(key, *fields)
            except Exception as e:
                logger.error(f"Redis HDEL error: {e}")
        return 0

    def lpush(self, key: str, *values):
        if self.client:
            try:
                return self.client.lpush(key, *values)
            except Exception as e:
                logger.error(f"Redis LPUSH error: {e}")
        return 0
    
    def rpush(self, key: str, *values):
        if self.client:
            try:
                return self.client.rpush(key, *values)
            except Exception as e:
                logger.error(f"Redis RPUSH error: {e}")
        return 0
    
    def lrange(self, key: str, start: int, end: int):
        if self.client:
            try:
                return self.client.lrange(key, start, end)
            except Exception as e:
                logger.error(f"Redis LRANGE error: {e}")
        return []
    
    def ltrim(self, key: str, start: int, end: int):
        """Trim a list to the given range.

        NOTE: this was previously MISSING while gpt/engine.py called it inside
        a broad try/except — the swallowed AttributeError meant chat-history
        lists were never trimmed AND (because the exception aborted the write
        batch before expire()) never given a TTL, growing unbounded.
        """
        if self.client:
            try:
                return self.client.ltrim(key, start, end)
            except Exception as e:
                logger.error(f"Redis LTRIM error: {e}")
        return False

    def lpop(self, key: str, count: int = 1):
        if self.client:
            try:
                return self.client.lpop(key, count)
            except Exception as e:
                logger.error(f"Redis LPOP error: {e}")
        return None
    
    def rpop(self, key: str, count: int = 1):
        if self.client:
            try:
                return self.client.rpop(key, count)
            except Exception as e:
                logger.error(f"Redis RPOP error: {e}")
        return None

    # ------------------------------------------------------------------ #
    # Sorted-set / pipeline / key methods required by the rate limiter.
    # These were previously MISSING, which made the rate limiter raise
    # AttributeError and fail. (P0 fix — see core/rate_limiter.py.)
    # ------------------------------------------------------------------ #
    def pipeline(self, transaction: bool = True):
        """Return a real redis pipeline, or a no-op stand-in if unavailable.

        The rate limiter prefers the raw client, but exposing pipeline() here
        keeps the wrapper a faithful, complete Redis surface.
        """
        if self.client:
            try:
                return self.client.pipeline(transaction=transaction)
            except Exception as e:
                logger.error(f"Redis PIPELINE error: {e}")
        return _NoOpPipeline()

    def zcard(self, key: str):
        if self.client:
            try:
                return self.client.zcard(key)
            except Exception as e:
                logger.error(f"Redis ZCARD error: {e}")
        return 0

    def zcount(self, key: str, min_score, max_score):
        if self.client:
            try:
                return self.client.zcount(key, min_score, max_score)
            except Exception as e:
                logger.error(f"Redis ZCOUNT error: {e}")
        return 0

    def zremrangebyscore(self, key: str, min_score, max_score):
        if self.client:
            try:
                return self.client.zremrangebyscore(key, min_score, max_score)
            except Exception as e:
                logger.error(f"Redis ZREMRANGEBYSCORE error: {e}")
        return 0

    def setex(self, key: str, seconds: int, value):
        if self.client:
            try:
                return self.client.setex(key, seconds, value)
            except Exception as e:
                logger.error(f"Redis SETEX error: {e}")
        return False

    def keys(self, pattern: str = "*"):
        if self.client:
            try:
                return self.client.keys(pattern)
            except Exception as e:
                logger.error(f"Redis KEYS error: {e}")
        return []

    def __getattr__(self, name):
        """Fallback: delegate any not-explicitly-wrapped method to the raw client.

        This guarantees the wrapper is never *missing* a Redis method (the root
        cause of the rate-limiter bug). Explicitly wrapped methods above take
        precedence; this only fires for attributes not found normally.

        Note: ``self.client`` is read via __dict__ to avoid recursing through
        __getattr__ during initialization.
        """
        client = self.__dict__.get("client")
        if client is not None and hasattr(client, name):
            return getattr(client, name)
        raise AttributeError(name)


class _NoOpPipeline:
    """Minimal pipeline stand-in used when Redis is unavailable.

    Buffers chained calls and returns an empty result list on execute(), so
    callers that expect a list (e.g. results[1]) degrade instead of crashing.
    """

    def __init__(self):
        self._n = 0

    def __getattr__(self, _name):
        def _chain(*_a, **_k):
            self._n += 1
            return self
        return _chain

    def execute(self):
        return [0] * self._n


# Export safe Redis client
safe_redis_client = SafeRedisClient(redis_client)

# For backward compatibility
redis_client = safe_redis_client

# Test function
def test_redis_connection():
    """Test Redis connection and return status"""
    try:
        if redis_client.ping():
            return {
                "status": "connected",
                "host": os.getenv("REDIS_HOST", "localhost"),
                "port": os.getenv("REDIS_PORT", "6379"),
                "available": True
            }
    except Exception as e:
        logger.error(f"Redis connection test failed: {e}")
    
    return {
        "status": "disconnected", 
        "error": "Connection failed",
        "available": False
    }