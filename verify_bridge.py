import asyncio
from services.engine_client import engine_client

async def verify_bridge():
    print("🚀 Verifying Python -> C# Bridge...")
    
    # 1. Check a random user status
    user_id = "test_user_123"
    print(f"Checking status for {user_id}...")
    status = await engine_client.get_user_status(user_id)
    print(f"✅ Status: {status}")
    
    # 2. Activate Pro via the ONE canonical path (amount-validated, idempotent).
    #    Pro = 30 TON canonically, so we pass a matching amount_ton; provider "ton".
    print("Activating Pro via Payment/complete...")
    import time as _t
    result = await engine_client.complete_payment(
        telegram_id=user_id,
        plan="Pro",
        provider="ton",
        external_id=f"bridge-test-{int(_t.time())}",
        duration_days=30,
        amount_ton=30.0,
    )
    print(f"✅ Activation: {result}")

    # 3. (Underpayment should be rejected) — uncomment to test:
    # bad = await engine_client.complete_payment(
    #     telegram_id=user_id, plan="Elite", provider="ton",
    #     external_id=f"bridge-underpay-{int(_t.time())}", amount_ton=1.0)
    # print(f"Underpay (expect permanent/4xx): {bad}")

    # 4. Check status again
    status = await engine_client.get_user_status(user_id)
    print(f"✅ New Status: {status}")

if __name__ == "__main__":
    try:
        asyncio.run(verify_bridge())
    except Exception as e:
        print(f"❌ Bridge Verification Failed: {e}")
        print("Ensure the C# backend is running on http://localhost:5090")
