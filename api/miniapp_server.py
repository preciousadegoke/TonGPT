"""
FastAPI server for TonGPT Mini-App
"""
from datetime import datetime, timedelta
from typing import Dict, Any
import logging
import asyncio
import os
import hashlib
import hmac
import json as _json
import time as _time
from urllib.parse import parse_qsl
import base64

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from services.analysis import analyze_token_ai, analyze_wallet_ai, calculate_risk_score, process_sentiment_data

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")


def verify_telegram_init_data(init_data: str) -> dict:
    """
    Verify Telegram WebApp initData HMAC.
    Returns parsed user dict or raises ValueError.
    """
    if not init_data:
        raise ValueError("Missing initData")

    params = dict(parse_qsl(init_data, strict_parsing=True))
    hash_value = params.pop("hash", None)
    if not hash_value:
        raise ValueError("Missing hash")

    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, hash_value):
        raise ValueError("Invalid initData signature")

    if _time.time() - int(params.get("auth_date", 0)) > 86400:
        raise ValueError("initData expired")

    return _json.loads(params["user"])

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan for FastAPI mini-app"""
    logger.info("🚀 Starting Mini-App API server...")
    # Start background cache maintenance and enhanced caching warmup.
    # This prevents unbounded memory growth from caches that otherwise never get cleaned.
    from services.analysis import start_cache_maintenance
    from services.analysis_cache import initialize_enhanced_caching

    start_cache_maintenance()
    initialize_enhanced_caching()
    yield
    logger.info("🛑 Stopping Mini-App API server...")

def create_miniapp_server() -> FastAPI:
    """Create and configure FastAPI mini-app server"""
    app = FastAPI(
        title="TonGPT Mini-App API",
        description="API endpoints for TonGPT Telegram Mini-App",
        version="1.0.0",
        lifespan=lifespan
    )

    from core.config import load_config
    config = load_config()
    allowed_origins = config.get("CORS_ALLOWED_ORIGINS", ["*"])
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # API IP Rate Limiting Middleware
    from fastapi import Request
    from starlette.middleware.base import BaseHTTPMiddleware
    import time
    
    class IPRateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Only rate limit /api defaults
            if request.url.path.startswith("/api/"):
                ip = request.client.host if request.client else "127.0.0.1"
                try:
                    from utils.redis_conn import redis_client
                    rc = getattr(redis_client, "client", redis_client)
                    if rc:
                        # 1. IP Ban check
                        ban_key = f"ip_ban:{ip}"
                        if rc.exists(ban_key):
                            from fastapi.responses import JSONResponse
                            return JSONResponse(status_code=403, content={"detail": "IP temporarily banned due to suspicious activity."})
                            
                        # 2. Concurrency Check
                        concurrency_key = f"active_conn:{ip}"
                        current_active = rc.incr(concurrency_key)
                        if current_active == 1:
                            rc.expire(concurrency_key, 60) # Fail-safe TTL
                        
                        if current_active > 15: # Max 15 concurrent requests per IP
                            rc.decr(concurrency_key)
                            from fastapi.responses import JSONResponse
                            return JSONResponse(status_code=429, content={"detail": "Too many concurrent connections from this IP."})
                        
                        try:
                            # 3. IP burst tracking
                            burst_key = f"miniapp_burst:{ip}"
                            count = rc.incr(burst_key)
                            if count == 1:
                                rc.expire(burst_key, 60) # 60 seconds
                            
                            if count > 60: # Max 60 requests per minute per IP to miniapp
                                logger.warning(f"BLOCKED Miniapp IP {ip} (Rate Limit Exceeded)")
                                from fastapi.responses import JSONResponse
                                # H-13: decrement BEFORE returning so counter doesn't leak
                                return JSONResponse(status_code=429, content={"detail": "Slow down! Too many requests."})
                                
                            return await call_next(request)
                        finally:
                            try:
                                rc.decr(concurrency_key)
                            except Exception:
                                pass
                except Exception as e:
                    logger.debug(f"IP Rate limit middleware error: {e}")
            
            return await call_next(request)
            
    app.add_middleware(IPRateLimitMiddleware)

    # Mount static files for the mini-app
    import os as _os
    if _os.path.isdir("miniapp"):
        app.mount("/miniapp", StaticFiles(directory="miniapp"), name="miniapp")
    else:
        logger.warning("miniapp/ directory not found — static file serving disabled")
    
    return app

# Create the app instance
miniapp = create_miniapp_server()

# ==================== MINI-APP API ROUTES ====================

async def _get_memecoin_data() -> list:
    """Shared memecoin formatting logic for /api/scan and /api/memecoins."""
    try:
        from utils.scanner import scan_memecoins

        tokens = await scan_memecoins(limit=5)
        return [
            {
                "name": token["symbol"],
                "symbol": token["symbol"],
                "price": f"${token['price']:.4f}",
                "change": f"{token['change']:+.1f}%",
                "lp": f"{token.get('lp', 1000000):,}",
                "holders": f"{token.get('holders', 5000):,}",
                "age": token.get("age", "1w"),
                "volume": f"{token.get('volume', 500000):,}",
            }
            for token in tokens
        ]
    except ImportError:
        logger.warning("⚠ Scanner module not found")
        return [
            {
                "name": "DOGCOIN",
                "symbol": "DOG",
                "price": "$0.0045",
                "change": "+12.5%",
                "lp": "1,250,000",
                "holders": "8,500",
                "age": "2d",
                "volume": "750,000",
            },
            {
                "name": "CATCOIN",
                "symbol": "CAT",
                "price": "$0.0032",
                "change": "-3.2%",
                "lp": "980,000",
                "holders": "6,200",
                "age": "5d",
                "volume": "420,000",
            },
        ]
    except Exception as e:
        logger.error(f"Memecoin scan failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.get("/")
async def serve_miniapp():
    """Serve the mini-app HTML with injected TONGPT_API_URL"""
    try:
        with open("miniapp/index.html", "r", encoding="utf-8") as f:
            html = f.read()
            
        api_url = os.environ.get("API_BASE_URL", "https://tongpt.loca.lt/api")
        injected_script = f'<script>window.TONGPT_API_URL = {_json.dumps(api_url)};</script></head>'
        html = html.replace('</head>', injected_script)
        
        return HTMLResponse(content=html)
    except Exception as e:
        logger.error(f"Error serving mini-app HTML: {e}")
        return FileResponse("miniapp/index.html")

@miniapp.get("/api/scan")
async def get_trending_coins():
    """Get trending coins for the mini-app"""
    return await _get_memecoin_data()

@miniapp.get("/api/whale")
async def get_whale_transactions():
    """Get whale transactions for the mini-app"""
    try:
        from services.tonapi import get_transactions
        transactions = await get_transactions(limit=5)
        return [
            {
                "wallet": tx["sender"],
                "amount": f"{tx['amount']:,}",
                "token": tx.get("token", "TON"),
                "time": (datetime.now() - timedelta(minutes=i*5)).strftime("%H:%M:%S"),
                "direction": tx.get("direction", "buy")
            } for i, tx in enumerate(transactions)
        ]
    except ImportError:
        logger.warning("⚠ TON API service not found")
        return [
            {
                "wallet": "UQ...abc123",
                "amount": "50,000",
                "token": "TON",
                "time": "12:34:56",
                "direction": "buy"
            }
        ]
    except Exception as e:
        logger.error(f"❌ Whale API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.get("/api/ston")
async def get_ston_pools():
    """Get STON.fi pools for the mini-app"""
    try:
        from services.stonfi_api import fetch_top_ston_pools
        pools = await fetch_top_ston_pools()
        return [
            {
                "pair": f"{pool['token0']}/{pool['token1']}",
                "apr": f"{pool['apr']}",
                "tvl": f"{pool['tvl_usd']:,}",
                "volume": f"{pool['volume']:,}" if pool.get("volume") else f"{pool['tvl_usd'] * 0.25:,}"
            } for pool in pools
        ]
    except ImportError:
        logger.warning("⚠ STON.fi API service not found")
        return [
            {
                "pair": "TON/USDT",
                "apr": "15.2%",
                "tvl": "2,500,000", 
                "volume": "850,000"
            }
        ]
    except Exception as e:
        logger.error(f"❌ STON API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.get("/api/X/sentiment")
async def get_X_sentiment():
    """Get X sentiment analysis for mini-app"""
    try:
        from services.tweet_sentiment import analyze_tweets
        posts = analyze_tweets()
        if not posts:
            return {"sentiment": "neutral", "posts": [], "summary": "No recent data"}
        
        # Calculate overall sentiment
        bullish = len([p for p in posts if p['sentiment'] == 'bullish'])
        bearish = len([p for p in posts if p['sentiment'] == 'bearish'])
        neutral = len(posts) - bullish - bearish
        
        overall = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"
        
        return {
            "sentiment": overall,
            "posts": posts[:3],
            "summary": f"{bullish} bullish, {bearish} bearish, {neutral} neutral"
        }
    except Exception as e:
        logger.error(f"❌ X sentiment API error: {e}")
        return {"sentiment": "neutral", "posts": [], "summary": "Data unavailable"}

@miniapp.post("/api/scan-token")
async def scan_token(request: Request, data: dict):
    """Scan token contract for detailed information"""
    # M-6: Validate Telegram initData before processing
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    try:
        verify_telegram_init_data(init_data)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Telegram init data")

    try:
        contract_address = data.get('address')
        
        if not contract_address:
            raise HTTPException(status_code=400, detail="Contract address is required")
        
        # H-11: analyze_token_ai is sync — offload to thread
        analysis = await asyncio.to_thread(analyze_token_ai, contract_address)
        
        return {
            "success": True,
            "data": analysis
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/scan-token: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.post("/api/ai-analysis")
async def get_ai_analysis(request: Request, data: dict):
    """Get AI-powered analysis for tokens or wallets"""
    # M-6: Validate Telegram initData before processing
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    try:
        verify_telegram_init_data(init_data)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Telegram init data")

    try:
        analysis_type = data.get('type', 'token')
        address = data.get('address')
        
        if not address:
            raise HTTPException(status_code=400, detail="Address is required")
        
        if analysis_type == 'token':
            analysis = await asyncio.to_thread(analyze_token_ai, address)
        elif analysis_type == 'wallet':
            analysis = await asyncio.to_thread(analyze_wallet_ai, address)
        else:
            raise HTTPException(status_code=400, detail="Invalid analysis type")
        
        return {
            "success": True,
            "data": analysis
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/ai-analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== WALLET AUTH WITH TON_PROOF VERIFICATION ====================

@miniapp.get("/api/wallet/generate-payload")
async def generate_wallet_proof_payload():
    """Generate a server-side nonce for ton_proof challenge"""
    import secrets as sec
    payload = f"tonproof-{sec.token_hex(32)}"
    
    # Store payload in Redis with 5-minute TTL for later verification
    try:
        from utils.redis_conn import redis_client
        if redis_client and redis_client.client:
            await redis_client.client.setex(f"tonproof:{payload}", 300, "valid")
        else:
            raise HTTPException(status_code=500, detail="Wallet verification service unavailable")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Could not store ton_proof nonce in Redis: {e}")
        raise HTTPException(status_code=500, detail="Wallet verification service temporarily unavailable")
    
    return {"payload": payload}


@miniapp.post("/api/wallet/auth")
async def authenticate_wallet(request: Request, data: dict):
    """
    Verify wallet ownership via TON Connect ton_proof, then forward to C# engine.
    
    The ton_proof is a signed message produced by the wallet that proves the user
    controls the private key corresponding to the wallet address.
    """
    ip = request.client.host if request.client else "127.0.0.1"
    
    init_data_header = request.headers.get("X-Telegram-Init-Data", "")
    try:
        tg_user = verify_telegram_init_data(init_data_header)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    telegram_id = tg_user["id"]
    address = data.get("Address")
    public_key = data.get("PublicKey")
    proof_json = data.get("Proof")
    state_init = data.get("StateInit")
    
    if not all([telegram_id, address, proof_json]):
        raise HTTPException(status_code=400, detail="Missing required fields: TelegramId, Address, Proof")
    
    # Block the dev bypass
    if proof_json == "SKIP_VERIFICATION_DEV":
        raise HTTPException(status_code=403, detail="Proof verification cannot be skipped")
    
    # Parse proof
    try:
        proof = _json.loads(proof_json)
    except _json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid proof format")
    
    # Validate proof structure
    required_fields = ["timestamp", "domain", "signature", "payload"]
    if not all(f in proof for f in required_fields):
        raise HTTPException(
            status_code=400,
            detail=f"Proof must contain: {', '.join(required_fields)}"
        )
    
    # Verify timestamp (proof must be less than 5 minutes old)
    import time
    proof_timestamp = int(proof["timestamp"])
    current_time = int(time.time())
    if abs(current_time - proof_timestamp) > 300:
        raise HTTPException(status_code=403, detail="Proof expired (older than 5 minutes)")
    
    # Verify nonce was generated by our server (if Redis available)
    payload_nonce = proof.get("payload", "")
    try:
        from utils.redis_conn import redis_client
        if redis_client and redis_client.client:
            # Atomic get-and-delete via Lua script to prevent TOCTOU nonce replay
            lua_script = """
            local val = redis.call('GET', KEYS[1])
            if val then
                redis.call('DEL', KEYS[1])
                return val
            end
            return nil
            """
            stored = await redis_client.client.eval(lua_script, 1, f"tonproof:{payload_nonce}")
            if stored is None:
                raise HTTPException(
                    status_code=403,
                    detail="Invalid or expired proof payload. Reconnect wallet to try again."
                )
        else:
            raise HTTPException(status_code=500, detail="Redis connection unavailable for validation")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Redis nonce check failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during nonce validation")
    
    # Verify Ed25519 signature (if nacl is available)
    verification_passed = False
    if public_key:
        try:
            import nacl.signing
            import nacl.exceptions
            
            # TON Connect ton_proof signature format:
            # message = "ton-proof-item-v2/" + address_workchain + address_hash + domain_len + domain + timestamp + payload
            domain = proof["domain"]
            domain_value = domain.get("value", "") if isinstance(domain, dict) else str(domain)
            domain_len = domain.get("lengthBytes", len(domain_value)) if isinstance(domain, dict) else len(domain_value)
            
            # Build the message that was signed
            # Prefix: "ton-proof-item-v2/"
            prefix = b"ton-proof-item-v2/"
            
            # Parse address to get workchain and hash
            # Raw address format in TON Connect is workchain:hash (hex)
            addr_parts = address.split(":")
            if len(addr_parts) == 2:
                workchain = int(addr_parts[0]).to_bytes(4, byteorder='big', signed=True)
                addr_hash = bytes.fromhex(addr_parts[1])
            else:
                # Address may be in different format — skip crypto verification
                logger.warning(f"Unexpected address format: {address[:20]}...")
                verification_passed = False
                raise ValueError("Address not in raw format")
            
            # Build msg
            domain_len_bytes = domain_len.to_bytes(4, byteorder='little')
            timestamp_bytes = proof_timestamp.to_bytes(8, byteorder='little')
            payload_bytes = payload_nonce.encode('utf-8')
            
            msg = (
                prefix +
                workchain +
                addr_hash +
                domain_len_bytes +
                domain_value.encode('utf-8') +
                timestamp_bytes +
                payload_bytes
            )
            
            # Hash the message
            msg_hash = hashlib.sha256(msg).digest()
            
            # TON wraps with "ton-connect" prefix
            ton_connect_prefix = b"\xff\xffton-connect"
            full_msg = hashlib.sha256(ton_connect_prefix + msg_hash).digest()
            
            # Verify signature
            signature = base64.b64decode(proof["signature"])
            verify_key = nacl.signing.VerifyKey(bytes.fromhex(public_key))
            verify_key.verify(full_msg, signature)
            
            verification_passed = True
            logger.info(f"ton_proof signature verified for address {address[:20]}...")
            
        except nacl.exceptions.BadSignatureError:
            logger.warning(f"Invalid ton_proof signature for address {address[:20]}...")
            raise HTTPException(status_code=403, detail="Invalid wallet signature — ownership verification failed")
        except ImportError:
            raise RuntimeError(
                "PyNaCl is required for wallet verification. "
                "Install it: pip install PyNaCl"
            )
        except ValueError as ve:
            logger.error(f"Could not parse address for crypto verification: {ve}")
            raise HTTPException(status_code=400, detail="Invalid address format for verification")
        except Exception as e:
            logger.error(f"Unexpected error during ton_proof verification: {e}")
            raise HTTPException(status_code=500, detail="Verification error")
    else:
        logger.warning("No public key provided — cannot verify signature")
        raise HTTPException(status_code=400, detail="PublicKey is required for wallet verification")
    
    # Validate TON address format
    from core.security import SecurityManager
    security = SecurityManager()
    if not security.validate_ton_address(address):
        raise HTTPException(status_code=400, detail="Invalid TON address format")
    
    # Forward verified wallet to C# Engine
    try:
        from services.engine_client import engine_client
        result = await engine_client._post("Wallet/auth", {
            "TelegramId": telegram_id,
            "Address": address,
            "PublicKey": public_key or "",
            "Proof": "VERIFIED_BY_PYTHON_SERVER",
            "StateInit": state_init or ""
        })
        if result.get("error"):
            raise HTTPException(status_code=result.get("error", 500), detail=result.get("message", "Engine rejected wallet link"))
        logger.info(f"Wallet {address[:20]}... linked to user {telegram_id}")
        return {"status": "success", "message": "Wallet verified and linked", "verified": verification_passed}
    except Exception as e:
        logger.error(f"Failed to forward wallet auth to engine: {e}")
        raise HTTPException(status_code=500, detail="Failed to save wallet link")


@miniapp.get("/api/user/consent-status")
async def consent_status(request: Request):
    """Check if the user has accepted the latest Terms of Service"""
    try:
        tg_user = verify_telegram_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid initData")

    try:
        from services.engine_client import engine_client
        user = await engine_client.get_user(tg_user["id"])
        accepted = user is not None and user.get("consentVersion") == "v1"
    except Exception:
        # User doesn't exist yet — treat as not consented, not as an error
        accepted = False

    return {"accepted": accepted}

@miniapp.post("/api/user/record-consent")
async def record_consent(request: Request, body: dict):
    """Record that the user accepted the Terms of Service"""
    try:
        tg_user = verify_telegram_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid initData")

    try:
        from services.engine_client import engine_client
        version = body.get("version", "v1")
        result = await engine_client._post("User/recordConsent", {
            "TelegramId": str(tg_user["id"]),
            "Version": version
        })
        if result and result.get("status") == "Success":
            return {"ok": True}
        raise Exception("Engine failed to record consent")
    except Exception as e:
        logger.error(f"Error recording consent: {e}")
        raise HTTPException(status_code=500, detail="Failed to record consent")

@miniapp.get("/api/user/referral-token")
async def get_referral_token(request: Request):
    """Generate a referral token for the current user"""
    try:
        tg_user = verify_telegram_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid initData")

    try:
        from handlers.referral import generate_referral_token
        token = generate_referral_token(tg_user["id"])
        return {"token": token}
    except Exception as e:
        logger.error(f"Error generating referral token: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate referral token")

@miniapp.get("/api/subscription/payment-info")
async def get_payment_info(plan: str = "Pro"):
    """Get the wallet address for subscription payments"""
    address = os.environ.get("PAYMENT_WALLET_ADDRESS", "")
    if not address:
        raise HTTPException(status_code=500, detail="Payment address not configured")
    return {"address": address, "plan": plan}


@miniapp.get("/api/health")
async def miniapp_health_check():
    """Health check for mini-app API"""
    return {
        "status": "online",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "bot": "online",
            "api": "online",
        }
    }

@miniapp.get("/api/user/status")
async def get_user_status(request: Request):
    """Get user subscription status from C# Engine"""
    # M-6: Validate Telegram initData — extract telegram_id from verified data
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    try:
        tg_user = verify_telegram_init_data(init_data)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Telegram init data")

    telegram_id = tg_user["id"]

    try:
        from services.engine_client import engine_client
        user = await engine_client.get_user(telegram_id)
        
        if user:
            return {
                "plan": user.get("plan", "Free"),
                "expiry": user.get("expiry"),
                "is_premium": user.get("plan") in ["Pro", "Whale"]
            }
        return {"plan": "Free", "expiry": None, "is_premium": False}
    except Exception as e:
        logger.error(f"❌ Error fetching user status: {e}")
        return {"plan": "Free", "expiry": None, "is_premium": False, "error": str(e)}

# Route Aliases for Frontend Compatibility
# Route Aliases for Frontend Compatibility
@miniapp.get("/api/memecoins")
async def get_memecoins_alias():
    """Alias for /api/scan"""
    return await _get_memecoin_data()

@miniapp.get("/api/trending")
async def get_trending_alias():
    """Alias for /api/ston"""
    try:
        from services.stonfi_api import fetch_top_ston_pools
        pools = await fetch_top_ston_pools()
        return [
            {
                "pair": f"{pool['token0']}/{pool['token1']}",
                "apr": f"{pool['apr']}",
                "tvl": f"{pool['tvl_usd']:,}",
                "volume": f"{pool['volume']:,}" if pool.get("volume") else f"{pool['tvl_usd'] * 0.25:,}"
            } for pool in pools
        ]
    except Exception as e:
        logger.error(f"❌ /api/trending failed: {e}")
        return [{"pair": "TON/USDT", "apr": "15.2%", "tvl": "2,500,000", "volume": "850,000"}]

@miniapp.get("/api/social")
async def get_social_alias():
    """Alias for /api/X/sentiment"""
    try:
        from services.tweet_sentiment import analyze_tweets
        posts = analyze_tweets()
        if not posts: return {"sentiment": "neutral", "posts": [], "summary": "No recent data"}
        
        bullish = len([p for p in posts if p['sentiment'] == 'bullish'])
        bearish = len([p for p in posts if p['sentiment'] == 'bearish'])
        neutral = len(posts) - bullish - bearish
        overall = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"
        
        return {
            "sentiment": overall,
            "posts": posts[:3],
            "summary": f"{bullish} bullish, {bearish} bearish, {neutral} neutral"
        }
    except Exception as e:
        logger.error(f"❌ /api/social failed: {e}")
        return {"sentiment": "neutral", "posts": [], "summary": "Data unavailable"}