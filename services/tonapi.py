import os
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TONAPI_BASE_URL = "https://tonapi.io/v2"  # You can change this if you use a different TON API provider
TONAPI_KEY = os.getenv("TONAPI_KEY")  # Make sure this is in your .env file

HEADERS = {
    "Authorization": f"Bearer {TONAPI_KEY}"
}


def get_wallet_info(address: str) -> dict:
    """
    Get basic wallet info like balance and account state.
    """
    url = f"{TONAPI_BASE_URL}/accounts/{address}"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()


def get_jettons(address: str) -> dict:
    """
    Fetch jettons (tokens) owned by a wallet.
    """
    url = f"{TONAPI_BASE_URL}/accounts/{address}/jettons"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()


def get_transactions(address: str, limit: int = 10) -> dict:
    """
    Get recent transactions from a wallet address.
    """
    url = f"{TONAPI_BASE_URL}/accounts/{address}/transactions?limit={limit}"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()


def resolve_dns(domain: str) -> dict:
    """
    Resolve a TON DNS domain like `ton.gpt`.
    """
    url = f"{TONAPI_BASE_URL}/dns/{domain}"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()
