import os
import hmac
import hashlib
import secrets
from typing import Dict, Any, Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import logging

logger = logging.getLogger(__name__)

class SecurityManager:
    def __init__(self):
        self.encryption_key = self._get_or_create_encryption_key()
        self.cipher = Fernet(self.encryption_key)
    
    def _get_or_create_encryption_key(self) -> bytes:
        """Get encryption key from environment or create new one"""
        key_env = os.getenv("ENCRYPTION_KEY")
        if key_env:
            return key_env.encode()
        
        # Generate new key for development
        password = os.getenv("MASTER_PASSWORD", "development_key").encode()
        salt = os.getenv("ENCRYPTION_SALT", "default_salt").encode()
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password))
        return key
    
    def encrypt_api_key(self, api_key: str) -> str:
        """Encrypt API key for storage"""
        try:
            encrypted = self.cipher.encrypt(api_key.encode())
            return base64.urlsafe_b64encode(encrypted).decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise
    
    def decrypt_api_key(self, encrypted_key: str) -> str:
        """Decrypt API key for use"""
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_key.encode())
            decrypted = self.cipher.decrypt(encrypted_bytes)
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise
    
    def verify_webhook_signature(self, payload: bytes, signature: str, secret: str) -> bool:
        """Verify webhook signature from payment providers"""
        try:
            expected = hmac.new(
                secret.encode(),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            # Remove 'sha256=' prefix if present
            if signature.startswith('sha256='):
                signature = signature[7:]
            
            return hmac.compare_digest(expected, signature)
        except Exception as e:
            logger.error(f"Signature verification failed: {e}")
            return False
    
    def generate_payment_token(self, user_id: int, amount: float, tier: str) -> str:
        """Generate secure payment token"""
        timestamp = str(int(time.time()))
        data = f"{user_id}:{amount}:{tier}:{timestamp}"
        
        token = hmac.new(
            os.getenv("PAYMENT_SECRET", "default_secret").encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return f"{timestamp}:{token}"
    
    def verify_payment_token(self, user_id: int, amount: float, tier: str, token: str) -> bool:
        """Verify payment token"""
        try:
            timestamp, expected_token = token.split(':', 1)
            
            # Check if token is not too old (1 hour max)
            import time
            if int(time.time()) - int(timestamp) > 3600:
                return False
            
            data = f"{user_id}:{amount}:{tier}:{timestamp}"
            actual_token = hmac.new(
                os.getenv("PAYMENT_SECRET", "default_secret").encode(),
                data.encode(),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(expected_token, actual_token)
        except Exception as e:
            logger.error(f"Token verification failed: {e}")
            return False
    
    def validate_payment_amount(self, amount: float, tier: str) -> bool:
        """Validate payment amount with tolerance"""
        expected_amounts = {
            "basic": 5.0,
            "premium": 15.0
        }
        
        expected = expected_amounts.get(tier)
        if not expected:
            return False
        
        # Allow 2% tolerance for blockchain fees
        tolerance = expected * 0.02
        return abs(amount - expected) <= tolerance
    
    def sanitize_input(self, user_input: str, max_length: int = 1000) -> str:
        """Sanitize user input to prevent injection attacks"""
        if not user_input:
            return ""
        
        # Truncate to max length
        sanitized = user_input[:max_length]
        
        # Remove potential SQL injection patterns
        dangerous_patterns = [
            "DROP", "DELETE", "INSERT", "UPDATE", "SELECT", 
            "UNION", "OR 1=1", "'; --", "<script", "javascript:",
            "onload=", "onerror=", "eval(", "exec("
        ]
        
        for pattern in dangerous_patterns:
            sanitized = sanitized.replace(pattern.lower(), "")
            sanitized = sanitized.replace(pattern.upper(), "")
        
        return sanitized.strip()
    
    def generate_api_rate_limit_key(self, user_id: int, endpoint: str) -> str:
        """Generate rate limit key for Redis"""
        return f"rate_limit:{user_id}:{endpoint}"
    
    def validate_ton_address(self, address: str) -> bool:
        """Validate TON wallet address format"""
        if not address:
            return False
        
        # Basic TON address validation
        if address.startswith(('EQ', 'UQ', 'kQ')):
            # Remove prefix and check base64
            try:
                addr_without_prefix = address[2:]
                base64.b64decode(addr_without_prefix + "==")  # Add padding
                return len(addr_without_prefix) >= 44
            except:
                return False
        
        return False

# Global security manager instance
security_manager = SecurityManager()

# Utility functions for easy access
def encrypt_sensitive_data(data: str) -> str:
    """Encrypt sensitive data"""
    return security_manager.encrypt_api_key(data)

def decrypt_sensitive_data(encrypted_data: str) -> str:
    """Decrypt sensitive data"""
    return security_manager.decrypt_api_key(encrypted_data)

def verify_webhook(payload: bytes, signature: str, secret: str) -> bool:
    """Verify webhook signature"""
    return security_manager.verify_webhook_signature(payload, signature, secret)

def validate_payment(amount: float, tier: str, user_id: int, token: str = None) -> bool:
    """Comprehensive payment validation"""
    # Validate amount
    if not security_manager.validate_payment_amount(amount, tier):
        return False
    
    # Validate token if provided
    if token and not security_manager.verify_payment_token(user_id, amount, tier, token):
        return False
    
    return True

def secure_user_input(user_input: str) -> str:
    """Secure user input"""
    return security_manager.sanitize_input(user_input)

# Rate limiting constants
RATE_LIMITS = {
    "free": {
        "requests_per_hour": 10,
        "ai_queries_per_day": 5,
        "scan_requests_per_hour": 3
    },
    "basic": {
        "requests_per_hour": 100,
        "ai_queries_per_day": 50,
        "scan_requests_per_hour": 20
    },
    "premium": {
        "requests_per_hour": 1000,
        "ai_queries_per_day": 500,
        "scan_requests_per_hour": 100
    }
}

# Payment validation constants
MAX_PAYMENT_AMOUNT = 100.0  # TON
MIN_PAYMENT_AMOUNT = 0.1    # TON
PAYMENT_TOKEN_EXPIRY = 3600  # 1 hour