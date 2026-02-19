import asyncio
from services.engine_client import engine_client

async def verify_bridge():
    print("🚀 Verifying Python -> C# Bridge...")
    
    # 1. Check a random user status
    user_id = "test_user_123"
    print(f"Checking status for {user_id}...")
    status = await engine_client.get_user_status(user_id)
    print(f"✅ Status: {status}")
    
    # 2. Try to create an invoice
    print("Creating test invoice...")
    invoice = await engine_client.create_invoice(user_id, 5.0)
    print(f"✅ Invoice: {invoice}")
    
    # 3. Upgrade user
    print("Upgrading user to Pro...")
    success = await engine_client.upgrade_user(user_id, "Pro")
    print(f"✅ Upgrade Success: {success}")
    
    # 4. Check status again
    status = await engine_client.get_user_status(user_id)
    print(f"✅ New Status: {status}")

if __name__ == "__main__":
    try:
        asyncio.run(verify_bridge())
    except Exception as e:
        print(f"❌ Bridge Verification Failed: {e}")
        print("Ensure the C# backend is running on http://localhost:5090")
