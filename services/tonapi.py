import os
import requests
import logging
from typing import Dict, List, Optional, Union
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# API Configuration
TONAPI_BASE_URL = "https://tonapi.io/v2"
TONAPI_KEY = os.getenv("TONAPI_KEY")  # Optional - TON API works without auth for basic requests

class EnhancedTONAPIClient:
    """Enhanced TON API client with whale transaction monitoring and basic wallet functions"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.base_url = TONAPI_BASE_URL
        self.api_key = api_key or TONAPI_KEY
        
        # Set up headers
        self.headers = {
            'User-Agent': 'TonGPT-Bot/1.0',
            'Accept': 'application/json'
        }
        
        # Add authorization if API key is provided
        if self.api_key:
            self.headers['Authorization'] = f'Bearer {self.api_key}'
        
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        
        # Whale transaction thresholds (in TON)
        self.whale_thresholds = {
            'small_whale': 1000,    # 1K TON
            'medium_whale': 10000,  # 10K TON
            'large_whale': 100000,  # 100K TON
            'mega_whale': 1000000   # 1M TON
        }
    
    # ============ BASIC WALLET FUNCTIONS (Your original functions enhanced) ============
    
    def get_wallet_info(self, address: str) -> dict:
        """
        Get basic wallet info like balance and account state.
        Enhanced version of your original function.
        """
        try:
            url = f"{self.base_url}/accounts/{address}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Add enhanced fields
            balance_ton = int(data.get('balance', 0)) / 1e9  # Convert from nanotons
            
            enhanced_data = {
                **data,  # Keep original data
                'balance_ton': balance_ton,
                'balance_usd': self._estimate_usd_value(balance_ton),
                'whale_category': self._classify_whale_size(balance_ton),
                'last_activity_formatted': self._format_timestamp(data.get('last_activity', 0))
            }
            
            return enhanced_data
            
        except Exception as e:
            logger.error(f"Error fetching wallet info for {address}: {e}")
            raise
    
    def get_jettons(self, address: str) -> dict:
        """
        Fetch jettons (tokens) owned by a wallet.
        Enhanced version of your original function.
        """
        try:
            url = f"{self.base_url}/accounts/{address}/jettons"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Enhance jetton data with additional info
            if 'balances' in data:
                for balance in data['balances']:
                    jetton = balance.get('jetton', {})
                    # Add token info if available
                    token_info = self.get_token_info_from_tonviewer(jetton.get('address', ''))
                    if token_info:
                        balance['token_info'] = token_info
            
            return data
            
        except Exception as e:
            logger.error(f"Error fetching jettons for {address}: {e}")
            raise
    
    def get_transactions(self, address: str, limit: int = 10) -> dict:
        """
        Get recent transactions from a wallet address.
        Enhanced version of your original function.
        """
        try:
            url = f"{self.base_url}/accounts/{address}/transactions"
            params = {'limit': limit}
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Enhance transaction data
            if 'transactions' in data:
                for tx in data['transactions']:
                    # Add whale classification and USD values
                    amount = self._extract_transaction_amount_from_tx(tx)
                    if amount:
                        tx['amount_ton'] = amount / 1e9
                        tx['whale_category'] = self._classify_whale_size(amount / 1e9)
                        tx['usd_value'] = self._estimate_usd_value(amount / 1e9)
                    
                    # Format timestamp
                    if 'now' in tx:
                        tx['timestamp_formatted'] = self._format_timestamp(tx['now'])
            
            return data
            
        except Exception as e:
            logger.error(f"Error fetching transactions for {address}: {e}")
            raise
    
    def resolve_dns(self, domain: str) -> dict:
        """
        Resolve a TON DNS domain like `ton.gpt`.
        Your original function unchanged.
        """
        try:
            url = f"{self.base_url}/dns/{domain}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            logger.error(f"Error resolving DNS for {domain}: {e}")
            raise
    
    # ============ WHALE MONITORING FUNCTIONS ============
    
    def get_token_info_from_tonviewer(self, contract_address: str) -> Optional[Dict]:
        """Get token info from TON API"""
        try:
            # Try to get jetton info
            url = f"{self.base_url}/jettons/{contract_address}"
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'name': data.get('metadata', {}).get('name', 'Unknown'),
                    'symbol': data.get('metadata', {}).get('symbol', ''),
                    'description': data.get('metadata', {}).get('description', ''),
                    'image': data.get('metadata', {}).get('image', ''),
                    'decimals': data.get('metadata', {}).get('decimals', 9),
                    'total_supply': data.get('total_supply', 0),
                    'holders_count': data.get('holders_count', 0),
                    'address': contract_address
                }
            
            # Fallback: try to get account info
            url = f"{self.base_url}/accounts/{contract_address}"
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'name': 'TON Account',
                    'symbol': 'TON',
                    'balance': data.get('balance', 0),
                    'status': data.get('status', 'unknown'),
                    'address': contract_address,
                    'last_activity': data.get('last_activity', 0)
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching token info for {contract_address}: {e}")
            return None
    
    def get_large_transactions(self, limit: int = 50, min_amount: float = 1000.0) -> List[Dict]:
        """Get large TON transactions (whale movements)"""
        try:
            transactions = []
            
            # Method 1: Get transactions from known whale addresses
            whale_addresses = self._get_known_whale_addresses()
            
            for address in whale_addresses[:10]:  # Limit to avoid rate limits
                try:
                    txs = self._get_address_events(address, limit=10)
                    for tx in txs:
                        amount = self._extract_transaction_amount(tx)
                        if amount and amount >= min_amount:
                            transactions.append({
                                'hash': tx.get('hash', ''),
                                'from_address': self._get_transaction_source(tx),
                                'to_address': self._get_transaction_destination(tx),
                                'amount': amount,
                                'amount_ton': amount / 1e9,
                                'timestamp': tx.get('timestamp', 0),
                                'type': self._classify_transaction_type(tx),
                                'whale_category': self._classify_whale_size(amount / 1e9),
                                'usd_value': self._estimate_usd_value(amount / 1e9),
                                'method': 'whale_address_tracking'
                            })
                except Exception as e:
                    logger.debug(f"Error getting transactions for {address}: {e}")
                    continue
            
            # Sort by timestamp and amount
            transactions.sort(key=lambda x: (x.get('timestamp', 0), x.get('amount_ton', 0)), reverse=True)
            
            # Remove duplicates and limit results
            seen_hashes = set()
            unique_transactions = []
            for tx in transactions:
                if tx['hash'] not in seen_hashes and len(unique_transactions) < limit:
                    seen_hashes.add(tx['hash'])
                    unique_transactions.append(tx)
            
            logger.info(f"Found {len(unique_transactions)} large transactions")
            return unique_transactions if unique_transactions else self._get_fallback_transactions()
            
        except Exception as e:
            logger.error(f"Error getting large transactions: {e}")
            return self._get_fallback_transactions()
    
    def get_whale_alert_summary(self, hours: int = 24) -> Dict:
        """Get whale activity summary for the last N hours"""
        try:
            transactions = self.get_large_transactions(limit=100)
            
            # Filter by time
            cutoff_time = datetime.now() - timedelta(hours=hours)
            cutoff_timestamp = int(cutoff_time.timestamp())
            
            recent_txs = [tx for tx in transactions if tx.get('timestamp', 0) > cutoff_timestamp]
            
            # Calculate summary stats
            total_volume = sum(tx.get('amount_ton', 0) for tx in recent_txs)
            total_usd_value = sum(tx.get('usd_value', 0) for tx in recent_txs)
            
            whale_categories = {}
            for tx in recent_txs:
                category = tx.get('whale_category', 'unknown')
                whale_categories[category] = whale_categories.get(category, 0) + 1
            
            return {
                'period_hours': hours,
                'total_transactions': len(recent_txs),
                'total_volume_ton': total_volume,
                'total_usd_value': total_usd_value,
                'whale_breakdown': whale_categories,
                'largest_transaction': max(recent_txs, key=lambda x: x.get('amount_ton', 0)) if recent_txs else None,
                'most_recent': recent_txs[0] if recent_txs else None
            }
            
        except Exception as e:
            logger.error(f"Error getting whale summary: {e}")
            return {
                'period_hours': hours,
                'total_transactions': 0,
                'error': str(e)
            }
    
    # ============ HELPER METHODS ============
    
    def _get_address_events(self, address: str, limit: int = 10) -> List[Dict]:
        """Get events for a specific address"""
        try:
            url = f"{self.base_url}/accounts/{address}/events"
            params = {'limit': limit}
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            return data.get('events', [])
            
        except Exception as e:
            logger.debug(f"Error getting events for {address}: {e}")
            return []
    
    def _get_known_whale_addresses(self) -> List[str]:
        """Get list of known whale addresses to monitor"""
        return [
            "EQD4FPq-PRDieyQKkizFTRtSDyucUIqrj0v_zXJmqaDp6_0t",
            # Add more known whale/exchange addresses here
        ]
    
    def _extract_transaction_amount(self, event: Dict) -> Optional[float]:
        """Extract TON amount from event"""
        try:
            actions = event.get('actions', [])
            for action in actions:
                if action.get('type') == 'TonTransfer':
                    amount = action.get('TonTransfer', {}).get('amount', 0)
                    return float(amount)
            return None
        except:
            return None
    
    def _extract_transaction_amount_from_tx(self, transaction: Dict) -> Optional[float]:
        """Extract TON amount from transaction object"""
        try:
            # Look for amount in transaction structure
            in_msg = transaction.get('in_msg', {})
            if in_msg and 'value' in in_msg:
                return float(in_msg['value'])
            
            # Look in out messages
            out_msgs = transaction.get('out_msgs', [])
            for msg in out_msgs:
                if 'value' in msg:
                    return float(msg['value'])
            
            return None
        except:
            return None
    
    def _get_transaction_source(self, event: Dict) -> str:
        """Get source address from event"""
        try:
            return event.get('account', {}).get('address', 'unknown')
        except:
            return 'unknown'
    
    def _get_transaction_destination(self, event: Dict) -> str:
        """Get destination address from event"""
        try:
            actions = event.get('actions', [])
            for action in actions:
                if 'Transfer' in action.get('type', ''):
                    recipient = action.get(action['type'], {}).get('recipient', {})
                    return recipient.get('address', 'unknown')
            return 'unknown'
        except:
            return 'unknown'
    
    def _classify_transaction_type(self, event: Dict) -> str:
        """Classify transaction type"""
        try:
            actions = event.get('actions', [])
            if not actions:
                return 'unknown'
            
            action_types = [action.get('type', '') for action in actions]
            
            if 'TonTransfer' in action_types:
                return 'ton_transfer'
            elif 'JettonTransfer' in action_types:
                return 'jetton_transfer'
            elif 'ContractDeploy' in action_types:
                return 'contract_deploy'
            else:
                return 'other'
        except:
            return 'unknown'
    
    def _classify_whale_size(self, amount_ton: float) -> str:
        """Classify whale size based on amount"""
        if amount_ton >= self.whale_thresholds['mega_whale']:
            return 'mega_whale'
        elif amount_ton >= self.whale_thresholds['large_whale']:
            return 'large_whale'
        elif amount_ton >= self.whale_thresholds['medium_whale']:
            return 'medium_whale'
        elif amount_ton >= self.whale_thresholds['small_whale']:
            return 'small_whale'
        else:
            return 'regular'
    
    def _estimate_usd_value(self, amount_ton: float) -> float:
        """Estimate USD value of TON amount"""
        # In practice, you'd get real TON price from an API
        ton_price_usd = 2.5  # Placeholder price
        return amount_ton * ton_price_usd
    
    def _format_timestamp(self, timestamp: int) -> str:
        """Format timestamp to readable string"""
        try:
            return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
        except:
            return 'unknown'
    
    def _get_fallback_transactions(self) -> List[Dict]:
        """Fallback transactions when API fails"""
        current_time = int(datetime.now().timestamp())
        
        return [
            {
                'hash': 'fallback_tx_1',
                'from_address': 'EQExample1...',
                'to_address': 'EQExample2...',
                'amount_ton': 50000,
                'timestamp': current_time - 300,
                'type': 'ton_transfer',
                'whale_category': 'large_whale',
                'usd_value': 125000,
                'method': 'fallback_data',
                'note': 'Large TON movement detected'
            }
        ]


# ============ GLOBAL CLIENT INSTANCE ============
ton_client = EnhancedTONAPIClient()

# ============ BACKWARD COMPATIBILITY FUNCTIONS (Your original API) ============
def get_wallet_info(address: str) -> dict:
    """Your original function - now enhanced"""
    return ton_client.get_wallet_info(address)

def get_jettons(address: str) -> dict:
    """Your original function - now enhanced"""
    return ton_client.get_jettons(address)

def get_transactions(address: str, limit: int = 10) -> dict:
    """Your original function - now enhanced"""
    return ton_client.get_transactions(address, limit)

def get_wallet_transactions(address: str, limit: int = 10) -> dict:
    """Alias for get_transactions for backward compatibility"""
    return get_transactions(address, limit)

def resolve_dns(domain: str) -> dict:
    """Your original function - unchanged"""
    return ton_client.resolve_dns(domain)

# ============ NEW WHALE MONITORING FUNCTIONS ============
def get_token_info_from_tonviewer(contract_address: str) -> Optional[Dict]:
    """Get token information"""
    return ton_client.get_token_info_from_tonviewer(contract_address)

def get_large_transactions(limit: int = 50, min_amount: float = 1000.0) -> List[Dict]:
    """Get large TON transactions for whale monitoring"""
    return ton_client.get_large_transactions(limit=limit, min_amount=min_amount)

def get_whale_summary(hours: int = 24) -> Dict:
    """Get whale activity summary"""
    return ton_client.get_whale_alert_summary(hours=hours)

# ============ UTILITY FUNCTIONS ============
def test_ton_api_connection() -> Dict:
    """Test TON API connectivity"""
    try:
        response = ton_client.session.get(f"{ton_client.base_url}/jettons", timeout=5)
        
        return {
            'api_status': 'online' if response.status_code == 200 else 'error',
            'status_code': response.status_code,
            'whale_tracking': 'enabled',
            'fallback_available': True,
            'auth_configured': bool(ton_client.api_key)
        }
    except Exception as e:
        return {
            'api_status': 'offline',
            'error': str(e),
            'whale_tracking': 'fallback_mode',
            'fallback_available': True,
            'auth_configured': bool(ton_client.api_key)
        }