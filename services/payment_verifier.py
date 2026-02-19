import hashlib
import hmac
import httpx
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class PaymentVerifier:
    def __init__(self, ton_api_key: str, webhook_secret: str):
        self.ton_api_key = ton_api_key
        self.webhook_secret = webhook_secret
        self.ton_api_base = "https://toncenter.com/api/v2"
    
    async def verify_ton_payment(self, transaction_hash: str, expected_amount: float, sender_wallet: str) -> bool:
        """Verify TON payment transaction"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.ton_api_base}/getTransactions",
                    params={
                        "address": sender_wallet,
                        "limit": 10,
                        "api_key": self.ton_api_key
                    }
                )
                
                if response.status_code != 200:
                    logger.error(f"TON API error: {response.status_code}")
                    return False
                
                data = response.json()
                transactions = data.get("result", [])
                
                for tx in transactions:
                    if (tx.get("hash") == transaction_hash and 
                        float(tx.get("value", 0)) / 1e9 >= expected_amount):
                        logger.info(f"Payment verified: {transaction_hash}")
                        return True
                
                return False
                
        except Exception as e:
            logger.error(f"Payment verification failed: {e}")
            return False
    
    def verify_telegram_webhook(self, data: str, signature: str) -> bool:
        """Verify Telegram payment webhook signature"""
        expected_signature = hmac.new(
            self.webhook_secret.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected_signature)