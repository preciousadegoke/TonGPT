import asyncio
import aiohttp
import sys

async def check_connection():
    url = "https://api.telegram.org"
    print(f"Testing connection to {url}...")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                print(f"Connection successful! Status: {response.status}")
                return True
    except Exception as e:
        print(f"Connection failed: {e}")
        return False

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(check_connection())
    except Exception as e:
        print(f"❌ Fatal error: {e}")
