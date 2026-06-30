import os
import hmac
import hashlib
import secrets
import time
from typing import Dict, Any, Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import logging
import struct

logger = logging.getLogger(__name__)


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc

class SecurityManager:
    def __init__(self):
        self.encryption_key = self._get_or_create_encryption_key()
        self.cipher = Fernet(self.encryption_key)
    
    def _get_or_create_encryption_key(self) -> bytes:
        """Get encryption key from environment or create new one"""
        key_env = os.getenv("ENCRYPTION_KEY")
        if key_env:
            return key_env.encode()
        
        # Generate key from master password — MUST be set in production
        password = os.getenv("MASTER_PASSWORD")
        salt = os.getenv("ENCRYPTION_SALT")
        if not password or not salt:
            logger.critical("MASTER_PASSWORD and ENCRYPTION_SALT must be set for encryption!")
            raise ValueError("Missing MASTER_PASSWORD or ENCRYPTION_SALT environment variable")
        password = password.encode()
        salt = salt.encode()
        
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
                secret.encode() if isinstance(secret, str) else secret,
                payload if isinstance(payload, bytes) else payload.encode(),
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
        
        payment_secret = os.getenv("PAYMENT_SECRET")
        if not payment_secret:
            raise ValueError("PAYMENT_SECRET environment variable must be set")
        token = hmac.new(
            payment_secret.encode() if isinstance(payment_secret, str) else payment_secret,
            data.encode() if isinstance(data, str) else data,
            hashlib.sha256
        ).hexdigest()
        
        return f"{timestamp}:{token}"
    
    def verify_payment_token(self, user_id: int, amount: float, tier: str, token: str) -> bool:
        """Verify payment token"""
        try:
            timestamp, expected_token = token.split(':', 1)
            
            # Check if token is not too old (1 hour max)
            if int(time.time()) - int(timestamp) > 3600:
                return False
            
            payment_secret = os.getenv("PAYMENT_SECRET")
            if not payment_secret:
                raise ValueError("PAYMENT_SECRET environment variable must be set")
            data = f"{user_id}:{amount}:{tier}:{timestamp}"
            actual_token = hmac.new(
                payment_secret.encode() if isinstance(payment_secret, str) else payment_secret,
                data.encode() if isinstance(data, str) else data,
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
        """Validate a TON address in EITHER friendly (EQ../UQ..) or raw (wc:hex) form.

        AUTH-004 fix: TON Connect delivers RAW addresses (``0:<hex>``) while users
        paste FRIENDLY ones (``EQ..``/``UQ..``). The old implementation only
        accepted friendly base64, so it 400'd every raw address coming out of the
        wallet — breaking the linking happy path. We now accept both by parsing
        through tonsdk's Address (which validates the CRC of friendly forms and
        the structure of raw forms) and fall back to the legacy CRC16 check.
        """
        if not address:
            return False
        # Primary: tonsdk understands both raw and friendly and validates the CRC.
        try:
            from tonsdk.utils import Address
            Address(address)
            return True
        except Exception:
            pass
        # Fallback: legacy friendly-only CRC16 check (kept for environments
        # without tonsdk and for defensive redundancy).
        b64 = address.replace("-", "+").replace("_", "/")
        pad = 4 - len(b64) % 4
        if pad != 4:
            b64 += "=" * pad
        try:
            raw = base64.b64decode(b64)
        except Exception:
            return False
        if len(raw) != 36:
            return False
        expected = struct.unpack(">H", raw[34:])[0]
        return crc16(raw[:34]) == expected


# ===========================================================================
#  TON address format helpers (AUTH-004)
#  One canonical INTERNAL form: friendly, url-safe, bounceable. Storing and
#  comparing wallets in this single form stops a raw vs friendly mismatch from
#  splitting one wallet into "two" identities or breaking the uniqueness check.
# ===========================================================================
def to_raw(address: str) -> str:
    """Return the raw ``wc:hex`` form of any TON address (raw or friendly in)."""
    from tonsdk.utils import Address
    return Address(address).to_string(False, False, False)


def to_friendly(address: str, *, bounceable: bool = True, testnet: bool = False) -> str:
    """Return the user-friendly, url-safe form (EQ../UQ..) of any TON address."""
    from tonsdk.utils import Address
    return Address(address).to_string(True, True, bounceable, testnet)


def normalize_address(address: str, *, testnet: Optional[bool] = None) -> str:
    """Canonical internal form used for storage + uniqueness comparisons.

    Always friendly + url-safe + bounceable so the SAME wallet always maps to the
    SAME string regardless of whether it arrived raw or friendly, EQ or UQ.
    """
    if testnet is None:
        testnet = os.getenv("TON_NETWORK", "mainnet").strip().lower() != "mainnet"
    return to_friendly(address, bounceable=True, testnet=testnet)


# ===========================================================================
#  TON Connect ton_proof verification (AUTH-001)
#  ---------------------------------------------------------------------------
#  SECURITY MODEL — why this actually proves ownership:
#    * The public key is NEVER taken from the client request. It is read from the
#      wallet's StateInit, which is bound to the address by the TON rule
#      ``account_address == hash(StateInit)``. An attacker cannot present a
#      victim's address together with their OWN StateInit (that would require a
#      SHA-256 collision), so any key we read here belongs to a StateInit that
#      genuinely hashes to the claimed address.
#    * The Ed25519 signature is then verified against that StateInit-derived key
#      over the exact TON Connect message. Success proves the connector holds the
#      private key committed in the contract that owns the address — real
#      ownership, not a self-asserted (address, pubkey) pair.
#  This is what closes the spoofing hole: signing with your own key while
#  claiming someone else's address now fails, because the signature is checked
#  against the victim's StateInit key, not your declared one.
# ===========================================================================
TON_PROOF_PREFIX = b"ton-proof-item-v2/"
TON_CONNECT_PREFIX = b"\xff\xffton-connect"

# Candidate bit offsets of the 256-bit public key inside a wallet data cell:
#   v3R1/R2 and v4R1/R2:  seqno(32) + subwallet_id(32)            = 64
#   v5 / W5:              flag(1) + seqno(32) + wallet_id(32)     = 65
# Trying several is SAFE: because the StateInit is hash-bound to the address,
# only the offset that yields the wallet's real key can verify the signature.
_PUBKEY_BIT_OFFSETS = (64, 65, 0, 96)


def _read_bits(buf: bytes, bit_offset: int, nbits: int) -> bytes:
    """Read ``nbits`` MSB-first bits starting at ``bit_offset`` from ``buf``."""
    out = bytearray((nbits + 7) // 8)
    for i in range(nbits):
        bi = bit_offset + i
        if bi // 8 >= len(buf):
            raise ValueError("state_init data cell too short for a public key")
        bit = (buf[bi // 8] >> (7 - (bi % 8))) & 1
        out[i // 8] |= bit << (7 - (i % 8))
    return bytes(out)


def _candidate_pubkeys_from_state_init(state_init_b64: str, address: str):
    """Parse the StateInit BoC, enforce ``hash(StateInit)==address``, and return
    candidate 256-bit public keys read from the wallet data cell.

    Raises ValueError if the StateInit does not hash to the claimed address —
    THIS is the anti-spoof binding.
    """
    from tonsdk.boc import Cell
    from tonsdk.utils import Address

    try:
        raw = base64.b64decode(state_init_b64)
        cell = Cell.one_from_boc(raw)
    except Exception as e:
        raise ValueError(f"Malformed StateInit BoC: {e}")

    addr = Address(address)
    if cell.bytes_hash() != addr.hash_part:
        raise ValueError("StateInit does not hash to the claimed address (binding failed)")

    if not cell.refs:
        raise ValueError("StateInit has no data cell")
    data_cell = cell.refs[1] if len(cell.refs) >= 2 else cell.refs[0]
    buf = bytes(data_cell.bits.get_top_upped_array())

    candidates = []
    for off in _PUBKEY_BIT_OFFSETS:
        try:
            candidates.append(_read_bits(buf, off, 256))
        except ValueError:
            continue
    if not candidates:
        raise ValueError("Could not read a public key from the StateInit data cell")
    return candidates


def verify_ton_proof(*, address: str, proof: dict, state_init: str,
                     allowed_domains: Optional[set] = None,
                     public_key: Optional[str] = None) -> str:
    """Cryptographically verify a TON Connect ton_proof and bind it to the
    address via the StateInit. Returns the CANONICAL (friendly) address on
    success; raises ValueError on ANY failure.

    Args:
        address:    wallet address (raw or friendly) as claimed by the client.
        proof:      the TON Connect proof dict (timestamp/domain/signature/payload).
        state_init: base64 BoC of the wallet StateInit (REQUIRED — the trust anchor).
        allowed_domains: if provided, proof.domain.value must be in this set.
        public_key: client-declared key — IGNORED for trust; used only for an
                    optional log/cross-check. Never trusted as the verifying key.
    """
    import nacl.signing
    import nacl.exceptions
    from tonsdk.utils import Address

    if not state_init:
        raise ValueError("StateInit is required to verify wallet ownership")

    # ---- message fields (use the values the wallet actually signed) ----
    domain = proof.get("domain")
    if isinstance(domain, dict):
        domain_value = str(domain.get("value", ""))
        domain_len = int(domain.get("lengthBytes", len(domain_value.encode("utf-8"))))
    else:
        domain_value = str(domain or "")
        domain_len = len(domain_value.encode("utf-8"))

    if allowed_domains and domain_value not in allowed_domains:
        raise ValueError(f"proof domain not allowed: {domain_value!r}")

    ts = int(proof["timestamp"])
    payload_nonce = str(proof.get("payload", ""))
    try:
        signature = base64.b64decode(proof["signature"])
    except Exception:
        raise ValueError("signature is not valid base64")

    addr = Address(address)
    wc_bytes = int(addr.wc).to_bytes(4, "big", signed=True)
    addr_hash = addr.hash_part

    message = (
        TON_PROOF_PREFIX
        + wc_bytes
        + addr_hash
        + domain_len.to_bytes(4, "little")
        + domain_value.encode("utf-8")
        + ts.to_bytes(8, "little")
        + payload_nonce.encode("utf-8")
    )
    full_msg = hashlib.sha256(TON_CONNECT_PREFIX + hashlib.sha256(message).digest()).digest()

    # The verifying key comes ONLY from the StateInit (hash-bound to the address).
    candidates = _candidate_pubkeys_from_state_init(state_init, address)
    for pk in candidates:
        try:
            nacl.signing.VerifyKey(pk).verify(full_msg, signature)
        except nacl.exceptions.BadSignatureError:
            continue
        # Optional, non-authoritative cross-check for observability only.
        if public_key:
            try:
                declared = bytes.fromhex(public_key.removeprefix("0x"))
                if declared != pk:
                    logger.warning("ton_proof: client public_key != StateInit key (ignored)")
            except ValueError:
                pass
        return normalize_address(address)

    raise ValueError("ton_proof signature did not verify against the StateInit key")


# ===========================================================================
#  Engine wallet-link assertion (ENG-001)
#  Replaces the "VERIFIED_BY_PYTHON_SERVER" magic string. After a real proof,
#  this server mints a short-lived HMAC token bound to (telegram_id, address).
#  The Engine validates the HMAC with the SAME secret, so a holder of
#  ENGINE_API_KEY alone — without WALLET_LINK_SIGNING_SECRET — cannot forge a
#  wallet link. Token shape (pipe-delimited, base64-free, trivial to parse in C#):
#       v1|<telegram_id>|<friendly_address>|<exp_unix>|<nonce>|<hmac_hex>
#  where hmac = HMAC_SHA256(secret, "v1|<tg>|<addr>|<exp>|<nonce>").
# ===========================================================================
def make_wallet_link_assertion(telegram_id, friendly_address: str, *, ttl_seconds: int = 60) -> str:
    secret = os.getenv("WALLET_LINK_SIGNING_SECRET", "")
    if not secret:
        raise RuntimeError("WALLET_LINK_SIGNING_SECRET is not set — cannot mint wallet-link assertion")
    exp = int(time.time()) + int(ttl_seconds)
    nonce = secrets.token_hex(8)
    body = f"v1|{telegram_id}|{friendly_address}|{exp}|{nonce}"
    sig = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}|{sig}"


# ===========================================================================
#  Sensitive user-action assertion (SEC-001)
#  Binds a privileged per-user action (GDPR export / erasure) to a specific
#  telegram_id with a short-lived HMAC, using the SAME shared secret as the
#  wallet assertion. The Engine requires this, so a holder of ENGINE_API_KEY
#  alone — without WALLET_LINK_SIGNING_SECRET — cannot export or delete an
#  arbitrary user's data. Format (the ``action`` namespaces it away from the
#  wallet token so the two can never be confused):
#       ua1|<action>|<telegram_id>|<exp_unix>|<nonce>|<hmac_hex>
# ===========================================================================
def make_user_action_assertion(telegram_id, action: str, *, ttl_seconds: int = 60) -> str:
    secret = os.getenv("WALLET_LINK_SIGNING_SECRET", "")
    if not secret:
        raise RuntimeError("WALLET_LINK_SIGNING_SECRET is not set — cannot mint user-action assertion")
    exp = int(time.time()) + int(ttl_seconds)
    nonce = secrets.token_hex(8)
    body = f"ua1|{action}|{telegram_id}|{exp}|{nonce}"
    sig = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}|{sig}"


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