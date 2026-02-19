"""
TON Wallet Manager for TonGPT
utils/ton_wallet.py
"""
import os
import asyncio
import logging
import hashlib
import time
from typing import Optional, Dict, List
from dataclasses import dataclass
import aiohttp

logger = logging.getLogger(__name__)

@dataclass
class PaymentAddress:
    """Payment address data"""
    address: str
    amount: float
    user_id: int
    created_at: float
    expires_at: float
    memo: Optional[str] = None

@dataclass
class Transaction:
    """Transaction data"""
    hash: str
    from_address: str
    to_address: str
    amount: float
    timestamp: float
    confirmed: bool
    memo: Optional[str] = None

class TonWallet:
    """TON Wallet manager for payment processing"""
    
    def __init__(self):
        """Initialize TON wallet manager"""
        # Get configuration from environment
        self.api_key = os.getenv('TON_API_KEY', '')
        self.wallet_address = os.getenv('TON_WALLET_ADDRESS', 'UQD...')  # Replace with actual wallet
        self.api_url = os.getenv('TON_API_URL', 'https://toncenter.com/api/v2/')
        
        # Payment tracking (in production, use Redis or database)
        self.pending_payments = {}
        self.processed_payments = set()
        
        # Session for HTTP requests
        self.session = None
        
        logger.info(f"TON Wallet initialized with address: {self.wallet_address[:10]}...")
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    'X-API-Key': self.api_key
                } if self.api_key else {}
            )
        return self.session
    
    async def close(self):
        """Close HTTP session"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def generate_payment_address(self, user_id: int, amount: float, memo: Optional[str] = None) -> str:
        """Generate payment address for user"""
        try:
            # Create unique payment identifier
            payment_id = hashlib.md5(
                f"{user_id}_{amount}_{time.time()}".encode()
            ).hexdigest()[:16]
            
            # For TON, we typically use the same wallet address with memo/comment
            # The memo helps identify which payment belongs to which user
            payment_memo = memo or f"TONGPT_{user_id}_{payment_id}"
            
            # Create payment record
            payment_address = PaymentAddress(
                address=self.wallet_address,
                amount=amount,
                user_id=user_id,
                created_at=time.time(),
                expires_at=time.time() + 3600,  # 1 hour expiry
                memo=payment_memo
            )
            
            # Store pending payment
            self.pending_payments[payment_id] = payment_address
            
            logger.info(f"Generated payment address for user {user_id}, amount {amount} TON")
            return self.wallet_address
            
        except Exception as e:
            logger.error(f"Error generating payment address: {e}")
            raise
    
    async def check_payment(self, payment_id: str) -> Optional[Transaction]:
        """Check if payment has been received"""
        try:
            if payment_id not in self.pending_payments:
                return None
            
            payment_info = self.pending_payments[payment_id]
            
            # Check if payment has expired
            if time.time() > payment_info.expires_at:
                del self.pending_payments[payment_id]
                return None
            
            # Get recent transactions for our wallet
            transactions = await self._get_wallet_transactions()
            
            # Look for matching transaction
            for tx in transactions:
                if (tx.to_address == self.wallet_address and 
                    tx.amount >= payment_info.amount and
                    payment_info.memo in (tx.memo or '') and
                    tx.hash not in self.processed_payments):
                    
                    # Mark as processed
                    self.processed_payments.add(tx.hash)
                    del self.pending_payments[payment_id]
                    
                    logger.info(f"Payment confirmed: {tx.hash} for user {payment_info.user_id}")
                    return tx
            
            return None
            
        except Exception as e:
            logger.error(f"Error checking payment {payment_id}: {e}")
            return None
    
    async def _get_wallet_transactions(self, limit: int = 50) -> List[Transaction]:
        """Get recent transactions for wallet"""
        try:
            session = await self._get_session()
            
            url = f"{self.api_url}getTransactions"
            params = {
                'address': self.wallet_address,
                'limit': limit,
                'to_lt': 0,
                'archival': True
            }
            
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"TON API error: {response.status}")
                    return []
                
                data = await response.json()
                
                if not data.get('ok'):
                    logger.error(f"TON API response not ok: {data}")
                    return []
                
                transactions = []
                for tx_data in data.get('result', []):
                    try:
                        # Parse transaction data
                        tx = self._parse_transaction(tx_data)
                        if tx:
                            transactions.append(tx)
                    except Exception as e:
                        logger.warning(f"Error parsing transaction: {e}")
                        continue
                
                return transactions
                
        except Exception as e:
            logger.error(f"Error fetching wallet transactions: {e}")
            return []
    
    def _parse_transaction(self, tx_data: Dict) -> Optional[Transaction]:
        """Parse transaction data from TON API"""
        try:
            # Extract relevant fields from TON API response
            in_msg = tx_data.get('in_msg')
            if not in_msg:
                return None
            
            amount = float(in_msg.get('value', 0)) / 1e9  # Convert from nanotons
            if amount <= 0:
                return None
            
            return Transaction(
                hash=tx_data.get('transaction_id', {}).get('hash', ''),
                from_address=in_msg.get('source', ''),
                to_address=in_msg.get('destination', ''),
                amount=amount,
                timestamp=float(tx_data.get('utime', 0)),
                confirmed=True,  # TON API only returns confirmed transactions
                memo=in_msg.get('message', '')
            )
            
        except Exception as e:
            logger.error(f"Error parsing transaction data: {e}")
            return None
    
    async def get_wallet_balance(self) -> float:
        """Get wallet balance"""
        try:
            session = await self._get_session()
            
            url = f"{self.api_url}getAddressBalance"
            params = {'address': self.wallet_address}
            
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    return 0.0
                
                data = await response.json()
                if data.get('ok'):
                    balance = float(data.get('result', 0)) / 1e9  # Convert from nanotons
                    return balance
                
                return 0.0
                
        except Exception as e:
            logger.error(f"Error getting wallet balance: {e}")
            return 0.0
    
    async def validate_address(self, address: str) -> bool:
        """Validate TON address format"""
        try:
            # Basic TON address validation
            if not address or len(address) < 48:
                return False
            
            # TON addresses typically start with UQ, EQ, or kQ
            if not address.startswith(('UQ', 'EQ', 'kQ')):
                return False
            
            # More thorough validation could be added here
            return True
            
        except Exception as e:
            logger.error(f"Error validating address {address}: {e}")
            return False
    
    async def send_transaction(self, to_address: str, amount: float, memo: Optional[str] = None) -> Optional[str]:
        """Send TON transaction (requires wallet private key - not implemented for security)"""
        # This would require wallet private key and signing
        # For security reasons, this is not implemented in this example
        # In production, use a secure wallet service or hardware wallet
        logger.warning("send_transaction not implemented for security reasons")
        return None
    
    def get_payment_url(self, address: str, amount: float, memo: Optional[str] = None) -> str:
        """Generate TON payment URL"""
        try:
            # Generate ton:// URL for TON wallets
            url = f"ton://transfer/{address}?amount={int(amount * 1e9)}"  # Convert to nanotons
            
            if memo:
                url += f"&text={memo}"
            
            return url
            
        except Exception as e:
            logger.error(f"Error generating payment URL: {e}")
            return f"ton://transfer/{address}"
    
    async def cleanup_expired_payments(self):
        """Clean up expired payment requests"""
        try:
            current_time = time.time()
            expired_payments = []
            
            for payment_id, payment_info in self.pending_payments.items():
                if current_time > payment_info.expires_at:
                    expired_payments.append(payment_id)
            
            for payment_id in expired_payments:
                del self.pending_payments[payment_id]
                logger.info(f"Cleaned up expired payment: {payment_id}")
            
            return len(expired_payments)
            
        except Exception as e:
            logger.error(f"Error cleaning up expired payments: {e}")
            return 0
    
    async def get_payment_status(self, user_id: int) -> Dict:
        """Get payment status for user"""
        try:
            user_payments = []
            for payment_id, payment_info in self.pending_payments.items():
                if payment_info.user_id == user_id:
                    user_payments.append({
                        'id': payment_id,
                        'amount': payment_info.amount,
                        'address': payment_info.address,
                        'memo': payment_info.memo,
                        'expires_at': payment_info.expires_at,
                        'status': 'pending'
                    })
            
            return {
                'user_id': user_id,
                'pending_payments': user_payments,
                'total_pending': len(user_payments)
            }
            
        except Exception as e:
            logger.error(f"Error getting payment status for user {user_id}: {e}")
            return {'user_id': user_id, 'pending_payments': [], 'total_pending': 0}
    
    async def health_check(self) -> bool:
        """Check if TON API is accessible"""
        try:
            balance = await self.get_wallet_balance()
            return balance >= 0  # Balance of 0 is valid
        except Exception as e:
            logger.error(f"TON wallet health check failed: {e}")
            return False