import asyncio
import aiohttp
import sys

SERVICES = [
    {"name": "Web UI", "url": "http://localhost:3000", "expected_status": 200},
    {"name": "Bot API", "url": "http://localhost:5080/api/health", "expected_status": 200},
    {"name": "Engine", "url": "http://localhost:5090/api/Subscription/status/123", "expected_status": [200, 404]} # 404 is user not found, but service is up
]

async def check_service(session, service):
    try:
        async with session.get(service["url"], timeout=5) as resp:
            status = resp.status
            expected = service["expected_status"]
            is_valid = status == expected if isinstance(expected, int) else status in expected
            
            if is_valid:
                print(f"[OK] {service['name']} is UP ({service['url']}) - Status: {status}")
                return True
            else:
                print(f"[FAIL] {service['name']} responded with {status} (Expected {expected})")
                return False
    except Exception as e:
        print(f"[FAIL] {service['name']} is DOWN ({service['url']}) - Error: {e}")
        return False

async def main():
    print("[INFO] Checking System Ports...")
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*[check_service(session, s) for s in SERVICES])
        
    if all(results):
        print("\n[SUCCESS] All Systems Operational!")
        sys.exit(0)
    else:
        print("\n[WARNING] Some services are not reachable.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
