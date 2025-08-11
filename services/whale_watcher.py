 # services/whale_watcher.py

import requests
from typing import List, Dict, Optional

TON_API_BASE = "https://tonapi.io/v2"  # Replace with your actual source or endpoint
HEADERS = {"Accept": "application/json"}

def fetch_recent_transactions(wallet_address: str, limit: int = 10) -> Optional[List[Dict]]:
    """
    Fetch recent transactions from a TON wallet.
    """
    try:
        url = f"{TON_API_BASE}/blockchain/accounts/{wallet_address}/transactions?limit={limit}"
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 200:
            data = response.json()
            return data.get("transactions", [])
        return None
    except Exception as e:
        print(f"[WhaleWatcher] Error fetching transactions: {e}")
        return None

def is_whale_transaction(tx: Dict, ton_threshold: float = 5000.0) -> bool:
    """
    Check if a transaction meets whale criteria.
    """
    amount_nano = int(tx.get("in_msg", {}).get("value", 0))
    amount_ton = amount_nano / 1e9  # Convert nanoton to TON
    return amount_ton >= ton_threshold

def extract_whale_activity(wallet_address: str, ton_threshold: float = 5000.0) -> List[Dict]:
    """
    Return whale transactions from a specific wallet.
    """
    txs = fetch_recent_transactions(wallet_address)
    if not txs:
        return []

    whales = []
    for tx in txs:
        if is_whale_transaction(tx, ton_threshold):
            whales.append({
                "amount_ton": int(tx["in_msg"]["value"]) / 1e9,
                "timestamp": tx.get("utime"),
                "tx_hash": tx.get("transaction_id", {}).get("hash"),
                "sender": tx["in_msg"].get("source"),
                "receiver": tx["in_msg"].get("destination")
            })
    return whales

