"""
Referral handling with anti-sybil protection.

Validates that referred users are genuine before counting them toward
the referrer's total. A referral is only counted when the referred user
has been active for >= 24 hours AND has issued >= 3 bot commands.
"""
from aiogram import Dispatcher, Router, types
from aiogram.filters import Command
import logging
import time
import hmac
import hashlib
import os

logger = logging.getLogger(__name__)

router = Router()

REFERRAL_MIN_AGE_SECONDS = 86400   # 24 hours
REFERRAL_MIN_COMMANDS = 3          # minimum interactions

REFERRAL_SECRET = os.getenv("REFERRAL_SECRET", "")

# ── helpers ──────────────────────────────────────────────────────────

def _redis():
    """Lazy import to avoid circular dependency."""
    from utils.redis_conn import redis_client
    return redis_client


async def record_referral_source(new_user_id: int, referrer_id: int):
    """Store the referral relationship when a new user /start's with a ref code.
    
    Does NOT immediately credit the referrer — the credit is deferred until
    the referred user passes the sybil checks (see validate_pending_referral).
    """
    rc = _redis()
    if not rc:
        return
    try:
        # Only record if this user hasn't already been referred
        if rc.get(f"referred_by:{new_user_id}"):
            return
        rc.set(f"referred_by:{new_user_id}", str(referrer_id))
        rc.set(f"ref_join_ts:{new_user_id}", str(int(time.time())))
        # Track pending referral for the referrer
        rc.sadd(f"pending_referrals:{referrer_id}", str(new_user_id))
        logger.info(f"Recorded pending referral: user {new_user_id} referred by {referrer_id}")
    except Exception as e:
        logger.error(f"Failed to record referral: {e}")


async def increment_user_commands(user_id: int):
    """Call this on every meaningful command to track activity for sybil checks."""
    rc = _redis()
    if not rc:
        return
    try:
        rc.incr(f"ref_cmd_count:{user_id}")
    except Exception:
        pass


async def validate_pending_referral(user_id: int):
    """Check if a pending referred user now passes sybil thresholds.
    
    If validated, credit the referrer's verified referral count and
    remove from pending set. This should be called periodically or
    after each user command.
    """
    rc = _redis()
    if not rc:
        return
    try:
        referrer_id = rc.get(f"referred_by:{user_id}")
        if not referrer_id:
            return
        referrer_id = referrer_id.decode() if isinstance(referrer_id, bytes) else str(referrer_id)
        
        # Already validated?
        if rc.get(f"ref_validated:{user_id}"):
            return
        
        # Check age threshold
        join_ts = rc.get(f"ref_join_ts:{user_id}")
        if not join_ts:
            return
        join_ts = int(join_ts)
        if (int(time.time()) - join_ts) < REFERRAL_MIN_AGE_SECONDS:
            return  # Too new
        
        # Check command count threshold
        cmd_count = rc.get(f"ref_cmd_count:{user_id}")
        cmd_count = int(cmd_count) if cmd_count else 0
        if cmd_count < REFERRAL_MIN_COMMANDS:
            return  # Not enough activity
        
        # ── Sybil checks passed — credit the referrer ──
        rc.incr(f"referrals:{referrer_id}")
        rc.set(f"ref_validated:{user_id}", "1")
        rc.srem(f"pending_referrals:{referrer_id}", str(user_id))
        
        logger.info(f"Referral validated: user {user_id} credited to referrer {referrer_id}")
        
    except Exception as e:
        logger.error(f"Referral validation error: {e}")


def generate_referral_token(referrer_id: int) -> str:
    key = REFERRAL_SECRET.encode() if isinstance(REFERRAL_SECRET, str) else REFERRAL_SECRET
    msg = str(referrer_id).encode()
    sig = hmac.new(key, msg, hashlib.sha256).hexdigest()[:16]
    return f"{referrer_id}_{sig}"


def verify_referral_token(token: str) -> int | None:
    try:
        referrer_id_str, sig = token.rsplit("_", 1)
        referrer_id = int(referrer_id_str)
        key = REFERRAL_SECRET.encode() if isinstance(REFERRAL_SECRET, str) else REFERRAL_SECRET
        msg = str(referrer_id).encode()
        expected = hmac.new(key, msg, hashlib.sha256).hexdigest()[:16]
        if hmac.compare_digest(sig, expected):
            return referrer_id
    except Exception:
        pass
    return None


def register_referral_handler(dp: Dispatcher):
    """Register the referral router with the dispatcher."""
    dp.include_router(router)