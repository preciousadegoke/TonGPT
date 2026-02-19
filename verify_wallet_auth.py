import requests
import json
import time

# Configuration
ENGINE_URL = "http://localhost:5090/api"
TEST_TELEGRAM_ID = 123456789
TEST_WALLET_ADDRESS = "EQD4FPq-PRDieyQKkizFTRtSDyua9DjOps7ebkbAqr5FzO_m"
TEST_PUBLIC_KEY = "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"

def print_pass(message):
    print(f"[PASS] {message}")

def print_fail(message):
    print(f"[FAIL] {message}")

def verify_wallet_auth():
    print(f"Testing Wallet Authentication on {ENGINE_URL}...")

    # 1. Sync User first (ensure user exists)
    print("1. Syncing Test User...")
    sync_payload = {
        "TelegramId": TEST_TELEGRAM_ID,
        "Username": "testuser",
        "FirstName": "Test",
        "LastName": "User"
    }
    try:
        resp = requests.post(f"{ENGINE_URL}/user/sync", json=sync_payload)
        resp.raise_for_status()
        print_pass("User Synced")
    except Exception as e:
        print_fail(f"User Sync Failed: {e}")
        return

    # 2. Authenticate Wallet
    print("2. Authenticating Wallet...")
    auth_payload = {
        "TelegramId": TEST_TELEGRAM_ID,
        "Address": TEST_WALLET_ADDRESS,
        "PublicKey": TEST_PUBLIC_KEY,
        "Proof": "{\"timestamp\": 1700000000, \"domain\": \"tongpt\", \"signature\": \"mock_sig\"}",
        "StateInit": "te6cckEBAQE..."
    }
    
    try:
        resp = requests.post(f"{ENGINE_URL}/wallet/auth", json=auth_payload)
        resp.raise_for_status()
        result = resp.json()
        if result.get("status") == "Success" and result.get("wallet") == TEST_WALLET_ADDRESS:
            print_pass("Wallet Auth Successful")
        else:
            print_fail(f"Wallet Auth Response Invalid: {result}")
            return
    except Exception as e:
        print_fail(f"Wallet Auth Request Failed: {e}")
        print(f"Response: {resp.text if 'resp' in locals() else 'N/A'}")
        return

    # 3. Verify User Record (GET)
    print("3. Verifying User Profile...")
    try:
        resp = requests.get(f"{ENGINE_URL}/wallet/status/{TEST_TELEGRAM_ID}")
        resp.raise_for_status()
        data = resp.json()
        
        if data.get("walletAddress") == TEST_WALLET_ADDRESS and data.get("isLinked") is True:
            print_pass("User Profile confirms Wallet Linked")
        else:
            print_fail(f"User Profile mismatch: {data}")
            return

    except Exception as e:
        print_fail(f"Get User Failed: {e}")
        return

    print("\nBackend Logic Verified!")

if __name__ == "__main__":
    # Ensure services are likely running (simple wait or check)
    try:
        requests.get(f"{ENGINE_URL}/user/1", timeout=1)
    except:
        print("WARNING: Engine might not be running on localhost:5090. If using Docker, ensure ports are mapped.")
    
    verify_wallet_auth()
