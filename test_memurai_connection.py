# test_memurai_connection.py
import redis
from utils.redis_conn import redis_client, safe_redis_client

def test_connections():
    print("🧪 Testing Connections...")
    
    # Test direct Redis client
    try:
        direct_client = redis.Redis(host='localhost', port=6379)
        direct_ping = direct_client.ping()
        print(f"✅ Direct Redis client: {direct_ping}")
    except Exception as e:
        print(f"❌ Direct Redis client failed: {e}")
    
    # Test your SafeRedisClient
    print(f"✅ Your SafeRedisClient available: {redis_client.available}")
    print(f"✅ Your SafeRedisClient ping: {redis_client.ping()}")
    
    # Test set/get operations
    test_key = "test:memurai"
    set_result = redis_client.set(test_key, "Hello Memurai!")
    get_result = redis_client.get(test_key)
    
    print(f"✅ SET operation: {set_result}")
    print(f"✅ GET operation: {get_result}")
    
    # Cleanup
    redis_client.delete(test_key)

if __name__ == "__main__":
    test_connections()