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

# RL-001: in-process per-IP limiter used as a FAIL-CLOSED fallback when Redis is
# unavailable, so the mini-app API is never left completely unthrottled (the old
# behaviour passed every request through when Redis was down).
import threading as _threading
_inproc_rl_lock = _threading.Lock()
_inproc_rl_hits: Dict[str, list] = {}


def _inproc_rate_allow(ip: str, limit_per_min: int) -> bool:
    now = _time.time()
    cutoff = now - 60
    with _inproc_rl_lock:
        q = _inproc_rl_hits.get(ip)
        if q is None:
            q = []
            _inproc_rl_hits[ip] = q
        # drop timestamps older than the window
        drop = 0
        for t in q:
            if t >= cutoff:
                break
            drop += 1
        if drop:
            del q[:drop]
        if len(q) >= limit_per_min:
            return False
        q.append(now)
        # bound memory: occasionally evict empty buckets
        if len(_inproc_rl_hits) > 10000:
            for k in [k for k, v in list(_inproc_rl_hits.items())[:2000] if not v]:
                _inproc_rl_hits.pop(k, None)
        return True


# RL-003: atomic INCR + first-time EXPIRE. Eliminates the window where a counter
# could exist without a TTL (process dies between incr and expire → key stuck).
_INCR_TTL_LUA = (
    "local v = redis.call('INCR', KEYS[1])\n"
    "if v == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end\n"
    "return v"
)


def _redis_incr_ttl(rc, key: str, ttl: int) -> int:
    return int(rc.eval(_INCR_TTL_LUA, 1, key, ttl))


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

    # MINI-001: shorten the replay window. A captured initData was valid for 24h;
    # default is now 1h (configurable). Shorter = smaller replay window.
    max_age = int(os.getenv("INITDATA_MAX_AGE_SECONDS", "3600"))
    if _time.time() - int(params.get("auth_date", 0)) > max_age:
        raise ValueError("initData expired")

    if "user" not in params:
        raise ValueError("initData missing user")
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
    
    from fastapi.responses import JSONResponse

    def _inproc_guard(ip):
        """Fail-closed in-process throttle (RL-001) when Redis can't be used."""
        limit = int(os.getenv("MINIAPP_INPROC_RATE_LIMIT", "30"))
        if not _inproc_rate_allow(ip, limit):
            return JSONResponse(status_code=429, content={"detail": "Service busy — slow down."})
        return None

    class IPRateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if not request.url.path.startswith("/api/"):
                return await call_next(request)

            ip = request.client.host if request.client else "127.0.0.1"
            rc = None
            try:
                from utils.redis_conn import redis_client
                rc = getattr(redis_client, "client", redis_client)
            except Exception:
                rc = None

            # RL-001: Redis unavailable -> FAIL CLOSED to the in-process limiter
            # rather than passing every request through unthrottled.
            if not rc:
                blocked = _inproc_guard(ip)
                return blocked if blocked is not None else await call_next(request)

            try:
                # 1) IP ban check.
                if rc.exists(f"ip_ban:{ip}"):
                    return JSONResponse(status_code=403, content={"detail": "IP temporarily banned due to suspicious activity."})

                # 2) Per-minute burst limit (atomic incr+TTL — RL-003).
                burst_key = f"miniapp_burst:{ip}"
                count = _redis_incr_ttl(rc, burst_key, 60)
                if count > 60:
                    logger.warning(f"BLOCKED Miniapp IP {ip} (rate limit exceeded)")
                    return JSONResponse(status_code=429, content={"detail": "Slow down! Too many requests."})

                # 3) Concurrency cap. Acquire (atomic incr+TTL), then guarantee
                #    release in finally (RL-002: no leak even if a later call throws).
                concurrency_key = f"active_conn:{ip}"
                active = _redis_incr_ttl(rc, concurrency_key, 60)
                try:
                    if active > 15:
                        return JSONResponse(status_code=429, content={"detail": "Too many concurrent connections from this IP."})
                    return await call_next(request)
                finally:
                    try:
                        rc.decr(concurrency_key)
                    except Exception:
                        pass
            except Exception as e:
                # Redis errored mid-request -> fail closed to the in-process limiter.
                logger.warning(f"IP rate limit Redis error; using in-process fallback: {e}")
                blocked = _inproc_guard(ip)
                return blocked if blocked is not None else await call_next(request)

    app.add_middleware(IPRateLimitMiddleware)

    # Mount static files for the mini-app.
    # The v2 app (Preact/Vite) builds to a `dist/` folder, so prefer that. We try,
    # in order: miniapp/dist (promoted v2), miniapp-v2/dist (v2 not yet renamed),
    # then a bare miniapp/ (legacy raw-static fallback). `html=True` serves
    # index.html for client-side routes.
    import os as _os
    _candidates = ["miniapp/dist", "miniapp-v2/dist", "miniapp"]
    _served = next((d for d in _candidates if _os.path.isdir(d)), None)
    if _served:
        app.mount("/miniapp", StaticFiles(directory=_served, html=True), name="miniapp")
        logger.info(f"Mini-App static files served from: {_served}")
    else:
        logger.warning("No mini-app build found (looked for miniapp/dist, miniapp-v2/dist, miniapp) — static serving disabled")

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
        # Use the async, non-blocking whale feed (no per-wallet address needed).
        from services.tonapi import get_large_transactions
        transactions = await get_large_transactions(limit=5, min_amount=1000.0)
        return [
            {
                "wallet": (tx.get("hash") or "UQ...")[:12],
                "amount": f"{int(tx.get('amount_ton', 0)):,}",
                "token": "TON",
                "time": (datetime.now() - timedelta(minutes=i * 5)).strftime("%H:%M:%S"),
                "direction": "buy",
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
    # NOTE: redis_client wraps sync redis.Redis — do NOT use await
    try:
        from utils.redis_conn import redis_client
        if redis_client and redis_client.client:
            redis_client.client.setex(f"tonproof:{payload}", 300, "valid")
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

    # Accept both the front-end's lower_snake_case keys and legacy PascalCase.
    def _field(*names):
        for n in names:
            v = data.get(n)
            if v not in (None, ""):
                return v
        return None

    address = _field("address", "Address")
    public_key = _field("public_key", "publicKey", "PublicKey")
    proof_raw = _field("proof", "Proof")
    # StateInit is now REQUIRED — it is the trust anchor that binds the public
    # key to the address (AUTH-001). TON Connect exposes it as walletStateInit.
    state_init = _field("state_init", "stateInit", "StateInit", "walletStateInit")

    if not all([telegram_id, address, proof_raw]):
        raise HTTPException(status_code=400, detail="Missing required fields: TelegramId, Address, Proof")
    if not state_init:
        raise HTTPException(
            status_code=400,
            detail="Missing StateInit — wallet ownership cannot be verified without it.",
        )

    # Block any attempt to short-circuit verification with a sentinel string.
    if isinstance(proof_raw, str) and proof_raw in ("SKIP_VERIFICATION_DEV", "VERIFIED_BY_PYTHON_SERVER"):
        raise HTTPException(status_code=403, detail="Proof verification cannot be skipped")

    # TON Connect delivers `proof` as an object; tolerate a JSON-encoded string too.
    if isinstance(proof_raw, dict):
        proof = proof_raw
    else:
        try:
            proof = _json.loads(proof_raw)
        except (_json.JSONDecodeError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid proof format")

    required_fields = ["timestamp", "domain", "signature", "payload"]
    if not all(f in proof for f in required_fields):
        raise HTTPException(
            status_code=400,
            detail=f"Proof must contain: {', '.join(required_fields)}",
        )

    # Timestamp: past-only with a small clock-skew allowance (no far-future proofs).
    import time
    proof_timestamp = int(proof["timestamp"])
    current_time = int(time.time())
    if proof_timestamp > current_time + 60 or (current_time - proof_timestamp) > 300:
        raise HTTPException(status_code=403, detail="Proof expired or not yet valid")

    # Anti-replay: the nonce must have been minted by us; consume it atomically.
    # NOTE: redis_client wraps sync redis.Redis — do NOT use await
    payload_nonce = proof.get("payload", "")
    try:
        from utils.redis_conn import redis_client
        if redis_client and redis_client.client:
            lua_script = """
            local val = redis.call('GET', KEYS[1])
            if val then
                redis.call('DEL', KEYS[1])
                return val
            end
            return nil
            """
            stored = redis_client.client.eval(lua_script, 1, f"tonproof:{payload_nonce}")
            if stored is None:
                raise HTTPException(
                    status_code=403,
                    detail="Invalid or expired proof payload. Reconnect wallet to try again.",
                )
        else:
            raise HTTPException(status_code=500, detail="Redis connection unavailable for validation")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Redis nonce check failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during nonce validation")

    # ── Cryptographic ownership proof (AUTH-001 / AUTH-004) ──────────────────
    # verify_ton_proof:
    #   1) enforces hash(StateInit) == address  (binds the key set to the address)
    #   2) reads the public key from the StateInit (NOT from the request)
    #   3) verifies the Ed25519 signature with that StateInit-derived key
    # and returns the canonical friendly address. Any failure → ValueError.
    from core.security import verify_ton_proof, make_wallet_link_assertion

    # Optional domain pinning (AUTH-002). Enforced when TONPROOF_ALLOWED_DOMAINS
    # is set; otherwise we warn so misconfig is visible but linking still works.
    allowed_domains = {d.strip() for d in os.getenv("TONPROOF_ALLOWED_DOMAINS", "").split(",") if d.strip()}
    if not allowed_domains:
        logger.warning("TONPROOF_ALLOWED_DOMAINS not set — domain pinning disabled")

    try:
        canonical_address = verify_ton_proof(
            address=address,
            proof=proof,
            state_init=state_init,
            allowed_domains=allowed_domains or None,
            public_key=public_key,
        )
    except ValueError as ve:
        logger.warning(f"ton_proof verification failed for user {telegram_id}: {ve}")
        raise HTTPException(status_code=403, detail="Wallet ownership verification failed")
    except Exception as e:  # noqa: BLE001 — crypto libs etc.
        logger.error(f"Unexpected error verifying ton_proof: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Verification error")

    logger.info(f"ton_proof verified; linking wallet for user {telegram_id}")

    # ── Forward to the Engine with a short-lived signed assertion (ENG-001) ──
    # The Engine no longer trusts any constant — it validates this HMAC, which
    # only THIS server (holding WALLET_LINK_SIGNING_SECRET) can mint after a real
    # proof. So even a holder of ENGINE_API_KEY cannot link a wallet on its own.
    try:
        assertion = make_wallet_link_assertion(telegram_id, canonical_address, ttl_seconds=60)
    except RuntimeError as e:
        logger.error(f"Cannot mint wallet-link assertion: {e}")
        raise HTTPException(status_code=503, detail="Wallet linking temporarily unavailable")

    try:
        from services.engine_client import engine_client
        result = await engine_client._post("Wallet/auth", {
            "TelegramId": telegram_id,
            "Address": canonical_address,
            "PublicKey": public_key or "",
            "Proof": assertion,
            "StateInit": state_init or "",
        })
    except Exception as e:
        logger.error(f"Failed to forward wallet auth to engine: {e}")
        raise HTTPException(status_code=500, detail="Failed to save wallet link")

    if isinstance(result, dict) and result.get("error"):
        status = result.get("error")
        status = status if isinstance(status, int) else 502
        raise HTTPException(status_code=status, detail=result.get("message", "Engine rejected wallet link"))

    logger.info(f"Wallet linked to user {telegram_id}")
    return {"status": "success", "message": "Wallet verified and linked", "verified": True}


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


@miniapp.post("/api/subscription/stars-invoice")
async def create_stars_invoice(request: Request, body: dict):
    """
    Mint a Telegram Stars invoice link for the Mini-App.

    The browser can't call the Bot API directly (no bot token client-side), so the
    Mini-App POSTs here and we return an `invoice_url` that the front-end opens with
    `Telegram.WebApp.openInvoice()`.

    This reuses the bot's EXISTING payment pipeline: the payload `premium_{plan_key}`
    is exactly what `handlers/pay.py`'s `pre_checkout_query` + `successful_payment`
    handlers already validate and use to activate the plan — so NO changes are
    needed there. Prices come from the single source of truth, `core/pricing.py`.
    """
    # 1. Authenticate the Telegram user (same HMAC check as every other route).
    try:
        tg_user = verify_telegram_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Telegram init data")

    # 2. Resolve the plan from the canonical pricing table.
    from core.pricing import PLANS
    plan_key = (body or {}).get("plan", "")
    plan = PLANS.get(plan_key)
    if not plan:
        raise HTTPException(status_code=400, detail="Invalid plan")

    # 3. Grab the live aiogram Bot instance (set via set_bot() at startup).
    from core.bot_instance import get_bot
    bot = get_bot()
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not ready")

    # 4. Create the invoice link.
    #    IMPORTANT: Telegram Stars (XTR) require an EMPTY provider_token, and the
    #    amount is the WHOLE number of Stars — NOT ×100 (see core/pricing.py XTR
    #    rule). This matches the bot's send_invoice path so both charge identically.
    from aiogram.types import LabeledPrice
    logger.info(f"Creating Stars invoice for user={tg_user.get('id')} plan={plan_key}")
    try:
        invoice_url = await bot.create_invoice_link(
            title=f"TonGPT {plan['name']}",
            description=f"Upgrade to {plan['name']} (1 month).",
            payload=f"premium_{plan_key}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=plan["name"], amount=plan["price_stars"])],
        )
    except Exception as e:
        logger.error(f"create_stars_invoice failed for plan={plan_key}: {e}")
        raise HTTPException(status_code=502, detail="Could not create invoice")

    return {"invoice_url": invoice_url}


@miniapp.get("/api/wallet/balance")
async def wallet_balance(address: str):
    """
    Return a wallet's TON balance (in TON, not nanotons) for the Mini-App Wallet
    screen. Proxying through the backend keeps any API keys server-side and avoids
    CORS. The front-end falls back to public toncenter if this route is absent, so
    it's optional but preferred.
    """
    if not address:
        raise HTTPException(status_code=400, detail="Missing address")

    network = os.getenv("TON_NETWORK", "mainnet").lower()
    base = (
        "https://testnet.toncenter.com/api/v2/getAddressBalance"
        if network == "testnet"
        else "https://toncenter.com/api/v2/getAddressBalance"
    )
    # Optional API key raises toncenter rate limits.
    api_key = os.getenv("TONCENTER_API_KEY", "")
    params = {"address": address}
    if api_key:
        params["api_key"] = api_key

    import httpx
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(base, params=params)
            data = r.json()
        if not data.get("ok"):
            raise HTTPException(status_code=502, detail="Balance unavailable")
        return {"balance": int(data["result"]) / 1_000_000_000}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"wallet_balance failed for {address}: {e}")
        raise HTTPException(status_code=502, detail="Balance unavailable")


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