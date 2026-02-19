import asyncio
import aiohttp
import sys

BASE_URL = "http://localhost:5080/api"

ENDPOINTS = [
    {"path": "/health", "desc": "Health Check"},
    {"path": "/user/status?telegram_id=123456789", "desc": "User Status"},
    {"path": "/memecoins", "desc": "Memecoins Alias"},
    {"path": "/trending", "desc": "Trending Alias"}
]

async def check_endpoint(session, endpoint):
    url = f"{BASE_URL}{endpoint['path']}"
    try:
        async with session.get(url, timeout=15) as resp:
            data = await resp.json() if resp.status == 200 else None
            status_desc = "[OK]" if resp.status == 200 else "[FAIL]"
            print(f"{status_desc} {endpoint['desc']} ({resp.status})")
            if resp.status != 200:
                print(f"   Error: {await resp.text()}")
            return resp.status == 200
    except Exception as e:
        print(f"[FAIL] {endpoint['desc']} Failed: {repr(e)}")
        return False

async def main():
    print(f"[INFO] Verifying MiniApp API at {BASE_URL}...")
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*[check_endpoint(session, e) for e in ENDPOINTS])
    
    if all(results):
        print("\n[SUCCESS] All Frontend API Endpoints Operational!")
        sys.exit(0)
    else:
        print("\n[WARNING] Some endpoints failed.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
