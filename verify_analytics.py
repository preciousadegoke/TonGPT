import requests
import json

ENGINE_URL = "http://localhost:5090/api"

def test_analytics():
    print(f"Testing Analytics Dashboard at {ENGINE_URL}/analytics/dashboard...")
    try:
        resp = requests.get(f"{ENGINE_URL}/analytics/dashboard")
        resp.raise_for_status()
        data = resp.json()
        print("[PASS] Dashboard Data Received:")
        print(json.dumps(data, indent=2))
        
        if "totalUsers" in data and "linkedWallets" in data:
             print("[PASS] Structure Valid")
        else:
             print("[FAIL] Structure Invalid")

    except Exception as e:
        print(f"[FAIL] Failed: {e}")

if __name__ == "__main__":
    test_analytics()
