import asyncio
import aiohttp
import json
import logging
import sys

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:5090/api"
TELEGRAM_ID = 123456789

async def test_user_sync(session):
    """Test creating and retrieving a user"""
    logger.info("Testing User Sync...")
    
    # payload
    data = {
        "telegramId": TELEGRAM_ID,
        "username": "test_user",
        "firstName": "Test",
        "lastName": "User"
    }
    
    # 1. Sync User
    async with session.post(f"{BASE_URL}/User/sync", json=data) as resp:
        if resp.status != 200:
            logger.error(f"Sync failed: {resp.status} - {await resp.text()}")
            return False
        logger.info("User Sync: OK")
        
    # 2. Get User
    async with session.get(f"{BASE_URL}/User/{TELEGRAM_ID}") as resp:
        if resp.status != 200:
            logger.error(f"Get User failed: {resp.status}")
            return False
        
        user_data = await resp.json()
        if str(user_data.get("telegramId")) != str(TELEGRAM_ID):
            logger.error(f"User data mismatch: {user_data}")
            return False
            
        logger.info(f"Get User: OK ({user_data})")
        return True

async def test_chat_flow(session):
    """Test saving and retrieving chat messages"""
    logger.info("Testing Chat Flow...")
    
    msg_data = {
        "telegramId": TELEGRAM_ID,
        "userMessage": "Hello AI",
        "aiResponse": "Hello Human",
        "timestamp": "2024-01-01T12:00:00Z"
    }
    
    # 1. Save Message
    async with session.post(f"{BASE_URL}/Chat/message", json=msg_data) as resp:
         if resp.status != 200:
            logger.error(f"Save Message failed: {resp.status}")
            return False
         logger.info("Save Message: OK")
         
    # 2. Get History
    async with session.get(f"{BASE_URL}/Chat/history/{TELEGRAM_ID}") as resp:
        if resp.status != 200:
             logger.error(f"Get History failed: {resp.status}")
             return False
             
        history = await resp.json()
        if not history or len(history) == 0:
             logger.error("History empty")
             return False
             
        logger.info(f"Get History: OK (Count: {len(history)})")
        return True

async def test_analytics(session):
    """Test logging activity"""
    logger.info("Testing Analytics Log...")
    
    log_data = {
        "telegramId": TELEGRAM_ID,
        "action": "test_action",
        "metadata": json.dumps({"foo": "bar"}),
        "success": True
    }
    
    async with session.post(f"{BASE_URL}/Analytics/log", json=log_data) as resp:
        if resp.status != 200:
            logger.error(f"Log Activity failed: {resp.status}")
            return False
        logger.info("Log Activity: OK")
        return True

async def main():
    logger.info(f"Connecting to {BASE_URL}...")
    
    async with aiohttp.ClientSession() as session:
        # Wait for API to be ready
        retries = 10
        for i in range(retries):
            try:
                async with session.get(f"{BASE_URL}/Subscription/status/{TELEGRAM_ID}") as resp:
                    if resp.status in [200, 404]: # 404 is fine (user might not exist yet)
                        logger.info("API is ready.")
                        break
            except Exception:
                logger.info(f"Waiting for API... ({i+1}/{retries})")
                await asyncio.sleep(2)
        else:
            logger.error("API not reachable.")
            sys.exit(1)

        # Run Tests
        success = True
        success &= await test_user_sync(session)
        success &= await test_chat_flow(session)
        success &= await test_analytics(session)
        
        if success:
            logger.info("ALL TESTS PASSED ✅")
            sys.exit(0)
        else:
            logger.error("SOME TESTS FAILED ❌")
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
