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
    
    def set(self, key: str, value, ex: int = None):
        if self.client:
            try:
                return self.client.set(key, value, ex=ex)
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