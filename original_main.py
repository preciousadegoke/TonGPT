from pydantic import BaseModel
from typing import Optional
import asyncio
import logging
import os
from pathlib import Path
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
import threading
from datetime import datetime, timedelta
import importlib

load_dotenv(dotenv_path=Path('.') / '.env')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
PAYMENT_TOKEN = os.getenv("PAYMENT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TON_API_KEY = os.getenv("TON_API_KEY")

X_API_KEY = os.getenv("X_API_KEY")
X_API_SECRET = os.getenv("X_API_SECRET")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET")
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

MINIAPP_PORT = int(os.getenv("MINIAPP_PORT", 8000))
MINIAPP_HOST = os.getenv("MINIAPP_HOST", "0.0.0.0")

missing_vars = []
if not BOT_TOKEN:
    missing_vars.append("BOT_TOKEN or TELEGRAM_BOT_TOKEN")

if not OPENROUTER_API_KEY and not OPENAI_API_KEY:
    missing_vars.append("OPENROUTER_API_KEY or OPENAI_API_KEY")

if not PAYMENT_TOKEN:
    logger.warning("⚠ PAYMENT_TOKEN not found — Telegram Stars payments will be disabled")
if not TON_API_KEY:
    logger.warning("⚠ TON_API_KEY not found — TON API rate limits may apply")

if not all([X_API_KEY, X_API_SECRET, X_BEARER_TOKEN]):
    logger.warning("⚠ X API credentials incomplete — X features will be limited")

if missing_vars:
    logger.critical(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
    raise ValueError("Required environment variables are missing.")

config = {
    "BOT_TOKEN": BOT_TOKEN,
    "PAYMENT_TOKEN": PAYMENT_TOKEN,
    "OPENROUTER_API_KEY": OPENROUTER_API_KEY,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "TON_API_KEY": TON_API_KEY,
    "X_API_KEY": X_API_KEY,
    "X_API_SECRET": X_API_SECRET,
    "X_ACCESS_TOKEN": X_ACCESS_TOKEN,
    "X_ACCESS_TOKEN_SECRET": X_ACCESS_TOKEN_SECRET,
    "X_BEARER_TOKEN": X_BEARER_TOKEN,
    "REDIS_HOST": REDIS_HOST,
    "REDIS_PORT": REDIS_PORT,
    "REDIS_PASSWORD": REDIS_PASSWORD,
    "REDIS_URL": REDIS_URL
}

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
        protect_content=False,
        allow_sending_without_reply=True
    )
)
dp = Dispatcher(storage=MemoryStorage())

gpt_handler = None

X_monitor = None

@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info("🚀 Starting Mini-App API server...")
    yield
    logger.info("🛑 Stopping Mini-App API server...")

miniapp = FastAPI(
    title="TonGPT Mini-App API",
    description="API endpoints for TonGPT Telegram Mini-App",
    version="1.0.0",
    lifespan=lifespan
)

miniapp.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

miniapp.mount("/miniapp", StaticFiles(directory="miniapp"), name="miniapp")

@miniapp.get("/")
async def serve_miniapp():

    return FileResponse("miniapp/index.html")

@miniapp.get("/api/scan")
async def get_trending_coins():

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
                "age": token.get('age', "1w"),
                "volume": f"{token.get('volume', 500000):,}"
            } for token in tokens
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
                "volume": "750,000"
            },
            {
                "name": "CATCOIN",
                "symbol": "CAT",
                "price": "$0.0032",
                "change": "-3.2%",
                "lp": "980,000",
                "holders": "6,200",
                "age": "5d",
                "volume": "420,000"
            }
        ]
    except Exception as e:
        logger.error(f"❌ Scan API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.get("/api/whale")
async def get_whale_transactions():

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
            },
            {
                "wallet": "UQ...def456",
                "amount": "25,000",
                "token": "TON",
                "time": "12:29:45",
                "direction": "sell"
            }
        ]
    except Exception as e:
        logger.error(f"❌ Whale API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.get("/api/ston")
async def get_ston_pools():

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
            },
            {
                "pair": "STON/TON",
                "apr": "22.8%",
                "tvl": "1,200,000",
                "volume": "420,000"
            }
        ]
    except Exception as e:
        logger.error(f"❌ STON API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.get("/api/X/sentiment")
async def get_X_sentiment():

    try:
        from services.tweet_sentiment import analyze_tweets
        posts = analyze_tweets()
        if not posts:
            return {"sentiment": "neutral", "posts": [], "summary": "No recent data"}

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

@miniapp.get("/api/X/alerts/{user_id}")
async def get_X_alerts_api(user_id: str):

    try:
        from utils.redis_conn import redis_client
        alerts = redis_client.lrange("X_alerts", 0, 4)
        return [
            {
                "username": alert_data["username"],
                "text": alert_data["text"][:80] + "...",
                "time": alert_data["timestamp"]
            } for alert in alerts if (alert_data := eval(alert.decode()))
        ]
    except Exception as e:
        logger.error(f"❌ X alerts API error: {e}")
        return []

@miniapp.get("/api/memecoins")
async def get_memecoins(limit: int = 20):

    try:

        try:
            from utils.scanner import scan_memecoins
            trending_tokens = await scan_memecoins(limit=limit)

            formatted_tokens = []
            for token in trending_tokens:
                formatted_tokens.append({
                    "symbol": token.get("symbol", "UNKNOWN"),
                    "name": token.get("name", token.get("symbol", "Unknown Token")),
                    "price": token.get("price", 0.0),
                    "change_24h": token.get("change", 0.0),
                    "volume_24h": token.get("volume", 0),
                    "market_cap": token.get("market_cap", token.get("volume", 0) * 10),
                    "contract": token.get("contract", f"EQD{token.get('symbol', 'XXX')}..."),
                    "holders": token.get("holders", 1000),
                    "verified": token.get("verified", False)
                })

        except ImportError:
            logger.warning("Scanner module not found, using mock data")

            formatted_tokens = [
                {
                    "symbol": "DOGS",
                    "name": "Dogs Token",
                    "price": 0.0012,
                    "change_24h": 15.6,
                    "volume_24h": 2450000,
                    "market_cap": 125000000,
                    "contract": "EQDExample1...",
                    "holders": 45000,
                    "verified": True
                },
                {
                    "symbol": "NOT",
                    "name": "Notcoin",
                    "price": 0.0089,
                    "change_24h": -8.2,
                    "volume_24h": 8900000,
                    "market_cap": 890000000,
                    "contract": "EQDExample2...",
                    "holders": 125000,
                    "verified": True
                },
                {
                    "symbol": "HMSTR",
                    "name": "Hamster",
                    "price": 0.0045,
                    "change_24h": 23.1,
                    "volume_24h": 1200000,
                    "market_cap": 45000000,
                    "contract": "EQDExample3...",
                    "holders": 32000,
                    "verified": False
                }
            ]

        whale_summary = {}
        try:
            from services.whale_watcher import get_whale_summary
            whale_summary = get_whale_summary(hours=24)
        except ImportError:
            logger.warning("Whale watcher service not found")
            whale_summary = {
                'total_volume_ton': 125000,
                'total_transactions': 24
            }
        except Exception as e:
            logger.error(f"Whale summary error: {e}")
            whale_summary = {'total_volume_ton': 0, 'total_transactions': 0}

        return {
            "success": True,
            "data": {
                "tokens": formatted_tokens[:limit],
                "whale_activity": {
                    "total_volume_24h": whale_summary.get('total_volume_ton', 0),
                    "large_transactions": whale_summary.get('total_transactions', 0)
                },
                "last_updated": datetime.now().isoformat()
            }
        }

    except Exception as e:
        logger.error(f"Error in /api/memecoins: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.post("/api/scan-token")
async def scan_token(data: dict):

    try:
        contract_address = data.get('address')

        if not contract_address:
            raise HTTPException(status_code=400, detail="Contract address is required")

        token_info = {}
        balance_info = {}
        whale_txs = []

        try:
            from services.tonviewer_api import get_token_info_from_tonviewer
            token_info = get_token_info_from_tonviewer(contract_address)
        except ImportError:
            logger.warning("TON Viewer API not found")
        except Exception as e:
            logger.error(f"Token info error: {e}")

        if not token_info:
            raise HTTPException(status_code=404, detail="Token not found or invalid address")

        try:
            from services.tonapi import get_wallet_info
            wallet_info = get_wallet_info(contract_address)
            balance_info = {
                "balance_ton": wallet_info.get('balance_ton', 0),
                "balance_usd": wallet_info.get('balance_usd', 0),
                "last_activity": wallet_info.get('last_activity_formatted', 'Unknown')
            }
        except ImportError:
            logger.warning("TON API wallet service not found")
        except Exception as e:
            logger.error(f"Wallet info error: {e}")

        try:
            from services.whale_watcher import extract_whale_activity
            whale_txs = extract_whale_activity(contract_address, ton_threshold=1000.0)
        except ImportError:
            logger.warning("Whale watcher not found")
        except Exception as e:
            logger.error(f"Whale activity error: {e}")

        risk_score = calculate_risk_score(token_info, whale_txs)

        return {
            "success": True,
            "data": {
                "token_info": token_info,
                "balance_info": balance_info,
                "whale_transactions": len(whale_txs),
                "recent_whale_activity": whale_txs[:5],
                "risk_score": risk_score,
                "scanned_at": datetime.now().isoformat()
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/scan-token: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.get("/api/trending")
async def get_trending():

    try:

        top_pools = []
        try:
            from services.stonfi_api import fetch_top_ston_pools
            top_pools = await fetch_top_ston_pools()
        except ImportError:
            logger.warning("STON.fi API not found")
        except Exception as e:
            logger.warning(f"STON.fi API error: {e}")

        large_transactions = []
        try:
            from services.tonapi import get_large_transactions
            large_transactions = get_large_transactions(limit=10, min_amount=5000.0)
        except ImportError:
            logger.warning("TON API large transactions not found")
        except Exception as e:
            logger.error(f"Large transactions error: {e}")

        market_trends = {
            "ton_price": 2.45,
            "ton_change_24h": 5.2,
            "total_market_cap": 8500000000,
            "total_volume_24h": 125000000,
            "trending_up": ["DOGS", "HMSTR", "SCALE"],
            "trending_down": ["NOT", "BOLT"]
        }

        return {
            "success": True,
            "data": {
                "market_overview": market_trends,
                "top_pools": top_pools,
                "whale_movements": large_transactions[:5],
                "last_updated": datetime.now().isoformat()
            }
        }

    except Exception as e:
        logger.error(f"Error in /api/trending: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.get("/api/social")
async def get_social_sentiment():

    try:

        tweet_analysis = []
        try:
            from services.tweet_sentiment import analyze_tweets
            tweet_analysis = analyze_tweets()
        except ImportError:
            logger.warning("Tweet sentiment analysis not found")
        except Exception as e:
            logger.error(f"Tweet analysis error: {e}")

        sentiment_summary = process_sentiment_data(tweet_analysis)

        influential_posts = [post for post in tweet_analysis if post.get('followers', 0) > 100000][:10]

        return {
            "success": True,
            "data": {
                "sentiment_summary": sentiment_summary,
                "influential_posts": influential_posts,
                "total_posts_analyzed": len(tweet_analysis),
                "last_updated": datetime.now().isoformat()
            }
        }

    except Exception as e:
        logger.error(f"Error in /api/social: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.post("/api/ai-analysis")
async def get_ai_analysis(data: dict):

    try:
        analysis_type = data.get('type', 'token')
        address = data.get('address')

        if not address:
            raise HTTPException(status_code=400, detail="Address is required")

        if analysis_type == 'token':
            analysis = analyze_token_ai(address)
        elif analysis_type == 'wallet':
            analysis = analyze_wallet_ai(address)
        else:
            raise HTTPException(status_code=400, detail="Invalid analysis type. Use 'token' or 'wallet'")

        return {
            "success": True,
            "data": analysis
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/ai-analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.get("/api/alerts/{user_id}")
async def get_user_alerts(user_id: str):

    try:
        from utils.redis_conn import redis_client
        alerts = redis_client.hgetall(f"alerts:{user_id}")
        return [
            {
                "token": key.split(":")[0],
                "condition": f"Price > ${value}",
                "status": "active" if redis_client.get(f"alerts:{user_id}:{key}:status") == "active" else "pending"
            } for key, value in alerts.items()
        ]
    except ImportError:
        logger.warning("⚠ Redis connection not available")
        return []
    except Exception as e:
        logger.error(f"❌ Alerts API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.get("/api/follow/{user_id}")
async def get_followed_wallets(user_id: str):

    try:
        from utils.redis_conn import redis_client
        wallets = redis_client.smembers(f"follows:{user_id}")
        return [
            {
                "address": wallet,
                "label": f"Wallet {i+1}",
                "lastTx": "Unknown",
                "time": (datetime.now() - timedelta(hours=i)).strftime("%H:%M:%S")
            } for i, wallet in enumerate(wallets)
        ]
    except ImportError:
        logger.warning("⚠ Redis connection not available")
        return []
    except Exception as e:
        logger.error(f"❌ Follow API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.get("/api/stats/{user_id}")
async def get_user_stats(user_id: str):

    try:
        from utils.redis_conn import redis_client
        referrals = int(redis_client.get(f"referral_count:{user_id}") or 0)
        return {
            "referrals": referrals,
            "earned": f"{referrals * 3} TON",
            "activeAlerts": len(redis_client.hgetall(f"alerts:{user_id}")),
            "followedWallets": len(redis_client.smembers(f"follows:{user_id}"))
        }
    except ImportError:
        logger.warning("⚠ Redis connection not available")
        return {
            "referrals": 0,
            "earned": "0 TON",
            "activeAlerts": 0,
            "followedWallets": 0
        }
    except Exception as e:
        logger.error(f"❌ Stats API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.post("/api/wallet/connect")
async def connect_wallet(data: dict):

    user_id = data.get("userId")
    address = data.get("address")
    try:
        from utils.redis_conn import redis_client
        redis_client.set(f"wallet:{user_id}", address)
        return {"status": "success", "message": "Wallet connected successfully"}
    except ImportError:
        logger.warning("⚠ Redis connection not available")
        return {"status": "error", "message": "Database unavailable"}
    except Exception as e:
        logger.error(f"❌ Wallet connect error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.post("/api/wallet/disconnect")
async def disconnect_wallet(data: dict):

    user_id = data.get("userId")
    try:
        from utils.redis_conn import redis_client
        redis_client.delete(f"wallet:{user_id}")
        return {"status": "success", "message": "Wallet disconnected successfully"}
    except ImportError:
        logger.warning("⚠ Redis connection not available")
        return {"status": "error", "message": "Database unavailable"}
    except Exception as e:
        logger.error(f"❌ Wallet disconnect error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@miniapp.get("/api/health")
async def miniapp_health_check():

    return {
        "status": "online",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "bot": "online",
            "api": "online",
            "X": "online" if all([X_API_KEY, X_BEARER_TOKEN]) else "limited"
        }
    }

def calculate_risk_score(token_info, whale_transactions):

    score = 50

    holders = token_info.get('holders_count', 0)
    if isinstance(holders, str):
        try:
            holders = int(holders.replace(',', ''))
        except:
            holders = 0

    if holders > 10000:
        score -= 20
    elif holders > 1000:
        score -= 10
    elif holders < 100:
        score += 30

    if len(whale_transactions) > 5:
        score += 15
    elif len(whale_transactions) > 2:
        score += 5

    if token_info.get('verified') or 'verified' in str(token_info.get('name', '')).lower():
        score -= 15

    return max(0, min(100, score))

def process_sentiment_data(tweet_data):

    if not tweet_data:
        return {
            "overall_sentiment": "neutral",
            "bullish_percentage": 33,
            "bearish_percentage": 33,
            "neutral_percentage": 34,
            "confidence": "low"
        }

    bullish_count = sum(1 for post in tweet_data if post.get('sentiment') == 'bullish')
    bearish_count = sum(1 for post in tweet_data if post.get('sentiment') == 'bearish')
    neutral_count = len(tweet_data) - bullish_count - bearish_count

    total = len(tweet_data)
    if total == 0:
        return process_sentiment_data([])

    bullish_pct = (bullish_count / total) * 100
    bearish_pct = (bearish_count / total) * 100
    neutral_pct = (neutral_count / total) * 100

    if bullish_pct > 50:
        overall = "bullish"
    elif bearish_pct > 50:
        overall = "bearish"
    else:
        overall = "neutral"

    return {
        "overall_sentiment": overall,
        "bullish_percentage": round(bullish_pct, 1),
        "bearish_percentage": round(bearish_pct, 1),
        "neutral_percentage": round(neutral_pct, 1),
        "confidence": "high" if total > 20 else "medium" if total > 10 else "low"
    }

def analyze_token_ai(contract_address):

    try:

        token_info = {}
        whale_txs = []

        try:
            from services.tonviewer_api import get_token_info_from_tonviewer
            token_info = get_token_info_from_tonviewer(contract_address)
        except:
            pass

        try:
            from services.whale_watcher import extract_whale_activity
            whale_txs = extract_whale_activity(contract_address)
        except:
            pass

        analysis = {
            "contract_address": contract_address,
            "analysis_type": "token",
            "risk_assessment": {
                "level": "medium",
                "score": calculate_risk_score(token_info or {}, whale_txs),
                "factors": []
            },
            "predictions": {
                "short_term": "neutral",
                "confidence": 0.65
            },
            "recommendations": [],
            "analyzed_at": datetime.now().isoformat()
        }

        if len(whale_txs) > 3:
            analysis["risk_assessment"]["factors"].append("High whale activity detected")

        if not token_info:
            analysis["risk_assessment"]["factors"].append("Limited token information available")
            analysis["recommendations"].append("Verify token contract manually")

        return analysis

    except Exception as e:
        return {
            "error": str(e),
            "analysis_type": "token",
            "analyzed_at": datetime.now().isoformat()
        }

def analyze_wallet_ai(wallet_address):

    try:

        wallet_info = {}
        transactions = {}

        try:
            from services.tonapi import get_wallet_info, get_transactions
            wallet_info = get_wallet_info(wallet_address)
            transactions = get_transactions(wallet_address, limit=50)
        except:
            pass

        balance_ton = wallet_info.get('balance_ton', 0)
        whale_category = wallet_info.get('whale_category', 'regular')

        analysis = {
            "wallet_address": wallet_address,
            "analysis_type": "wallet",
            "wallet_profile": {
                "category": whale_category,
                "balance_ton": balance_ton,
                "activity_level": "high" if len(transactions.get('transactions', [])) > 20 else "medium" if len(transactions.get('transactions', [])) > 5 else "low"
            },
            "behavior_analysis": {
                "trading_pattern": "active" if balance_ton > 1000 else "holder",
                "risk_level": "high" if whale_category in ['large_whale', 'mega_whale'] else "medium"
            },
            "insights": [],
            "analyzed_at": datetime.now().isoformat()
        }

        if whale_category != 'regular':
            analysis["insights"].append(f"This is a {whale_category.replace('_', ' ')} wallet")

        if balance_ton > 100000:
            analysis["insights"].append("Extremely large TON holdings detected")

        return analysis

    except Exception as e:
        return {
            "error": str(e),
            "analysis_type": "wallet",
            "analyzed_at": datetime.now().isoformat()
        }

def start_miniapp_server():

    try:
        uvicorn.run(
            miniapp,
            host=MINIAPP_HOST,
            port=MINIAPP_PORT,
            log_level="info",
            access_log=False
        )
    except Exception as e:
        logger.error(f"❌ Mini-app server error: {e}")

async def initialize_X_monitor():

    global X_monitor

    if not all([X_API_KEY, X_API_SECRET, X_BEARER_TOKEN]):
        logger.warning("⚠ X API credentials incomplete - monitoring disabled")
        return False

    try:
        from services.X_monitor import XMonitor
        X_monitor = XMonitor()
        logger.info("✅ X monitor initialized")

        original_send_alert = X_monitor.send_alert

        async def enhanced_send_alert(tweet):

            original_send_alert(tweet)

            await send_X_alert_to_users(tweet)

        X_monitor.send_alert = enhanced_send_alert
        return True

    except ImportError:
        logger.warning("⚠ X monitor module not found")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to initialize X monitor: {e}")
        return False

async def send_X_alert_to_users(tweet):

    try:
        from utils.redis_conn import redis_client
        import json

        premium_users = redis_client.smembers("premium_users")
        if not premium_users:
            return

        alert_message = (
            f"🚨 <b>X Alert!</b>\n\n"
            f"🐦 <b>@{tweet['username']}</b> mentioned TON:\n\n"
            f"💬 {tweet['text'][:200]}{'...' if len(tweet['text']) > 200 else ''}\n\n"
            f"❤️ {tweet.get('like_count', 0)} | 🔄 {tweet.get('retweet_count', 0)}"
        )

        redis_client.lpush("X_alerts", json.dumps({
            'username': tweet['username'],
            'text': tweet['text'][:100],
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'likes': tweet.get('like_count', 0),
            'retweets': tweet.get('retweet_count', 0)
        }))
        redis_client.ltrim("X_alerts", 0, 49)

        for user_id in premium_users:
            try:
                await bot.send_message(
                    chat_id=int(user_id.decode()),
                    text=alert_message,
                    parse_mode="HTML"
                )
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Failed to send X alert to user {user_id}: {e}")

    except Exception as e:
        logger.error(f"Error sending X alerts: {e}")

async def start_X_monitoring():

    if X_monitor:
        logger.info("🐦 Starting X monitoring service...")
        asyncio.create_task(X_monitor.monitor_influencer_tweets())
    else:
        logger.warning("⚠ X monitor not initialized - skipping background monitoring")

async def test_connections_on_startup():

    logger.info("🔍 Testing external service connections...")

    try:
        from utils.redis_conn import redis_client
        redis_client.ping()
        logger.info("✅ Redis connection successful")
    except ImportError:
        logger.warning("⚠ Redis module not found. Some features may be limited.")
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")

    try:
        if OPENROUTER_API_KEY:
            from gpt.engine import test_gpt_connection
            if await test_gpt_connection():
                logger.info("✅ OpenRouter GPT connection test passed")
            else:
                logger.error("❌ OpenRouter GPT connection test failed")
        elif OPENAI_API_KEY:
            logger.info("✅ Using OpenAI API as GPT provider")
        else:
            logger.error("❌ No GPT API key configured")
    except ImportError:
        logger.warning("⚠ GPT engine module not found. AI features will be disabled.")
    except Exception as e:
        logger.error(f"❌ GPT test error: {e}")

    try:
        from services.tonapi import test_ton_api_connection
        api_status = test_ton_api_connection()
        if api_status.get('api_status') == 'online':
            logger.info("✅ TON API connection successful")
        else:
            logger.warning(f"⚠ TON API connection issues: {api_status}")
    except ImportError:
        logger.warning("⚠ TON API service not found. Blockchain features will be limited.")
    except Exception as e:
        logger.error(f"❌ TON API test error: {e}")

    try:
        if X_monitor:

            client = X_monitor.client
            me = client.get_me()
            if me.data:
                logger.info(f"✅ X API connection successful (@{me.data.username})")
            else:
                logger.warning("⚠ X API connection issues")
        else:
            logger.warning("⚠ X monitor not initialized")
    except Exception as e:
        logger.error(f"❌ X API test error: {e}")

async def initialize_gpt_handler():

    global gpt_handler

    try:

        from handlers.enhanced_gpt_handler import EnhancedGPTHandler

        api_key = OPENROUTER_API_KEY or OPENAI_API_KEY
        model = "gpt-4" if OPENAI_API_KEY and not OPENROUTER_API_KEY else "openai/gpt-4"

        gpt_handler = EnhancedGPTHandler(api_key, model)
        logger.info("✅ Enhanced GPT handler initialized")

    except ImportError:
        logger.warning("⚠ Enhanced GPT handler not found. Basic responses only.")
        gpt_handler = None
    except Exception as e:
        logger.error(f"❌ Failed to initialize GPT handler: {e}")
        gpt_handler = None

def register_handler_safely(module_name: str, register_function: str, dp: Dispatcher) -> bool:

    try:
        if register_function == "router":

            imported = __import__(f"handlers.{module_name}", fromlist=["router"])
            router = getattr(imported, "router")
            dp.include_router(router)
        else:

            imported = __import__(f"handlers.{module_name}", fromlist=[register_function])
            register_func = getattr(imported, register_function)

            import inspect
            sig = inspect.signature(register_func)
            params = list(sig.parameters.keys())

            if len(params) == 1:
                register_func(dp)
            elif 'config' in params and 'gpt_handler' in params:
                register_func(dp, config, gpt_handler)
            elif 'config' in params:
                register_func(dp, config)
            elif 'gpt_handler' in params:
                register_func(dp, gpt_handler)
            else:
                register_func(dp)

        logger.info(f"✅ Registered handler: {module_name}")
        return True

    except ImportError as e:
        logger.warning(f"⚠ Module {module_name} not found: {e}")
        return False
    except AttributeError as e:
        logger.warning(f"⚠ Registration function {register_function} not found in {module_name}: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to register {module_name}: {e}")
        return False

try:
    from bot.commands import register_commands
    register_commands(dp)
    logger.info("✅ Core commands registered")
except Exception as e:
    logger.error(f"❌ Failed to register core commands: {e}")

handlers_to_register = [

    ("gpt_reply", "register_gpt_reply_handlers"),

    ("X_handler", "register_X_handlers"),

    ("pay", "register_pay_handlers"),

    ("whale", "register_whale_handlers"),
    ("alerts", "register_alerts_handlers"),
    ("wallet_watch", "register_wallet_handlers"),
    ("ston", "register_ston_handlers"),

]

registered_handlers = []
failed_handlers = []

async def register_all_handlers():

    global registered_handlers, failed_handlers

    logger.info("📦 Registering handler modules...")

    if gpt_handler:
        try:
            from handlers.enhanced_gpt_handler import handle_gpt_query

            @dp.message(lambda message: not message.text.startswith('/') if message.text else False)
            async def handle_general_message(message):

                await handle_gpt_query(message, gpt_handler)

            logger.info("✅ Enhanced GPT message handler registered")
        except Exception as e:
            logger.error(f"❌ Failed to register GPT message handler: {e}")

    for module_name, register_function in handlers_to_register:
        try:

            module = importlib.import_module(f'handlers.{module_name}')

            if hasattr(module, register_function):

                register_func = getattr(module, register_function)

                import inspect
                sig = inspect.signature(register_func)
                params = list(sig.parameters.keys())

                if len(params) == 1:
                    register_func(dp)
                elif 'config' in params and 'gpt_handler' in params:
                    register_func(dp, config, gpt_handler)
                elif 'config' in params:
                    register_func(dp, config)
                elif 'gpt_handler' in params:
                    register_func(dp, gpt_handler)
                else:
                    register_func(dp)

                registered_handlers.append(module_name)
                logger.info(f"✅ Registered handler: {module_name}")

            elif hasattr(module, 'router'):

                dp.include_router(module.router)
                registered_handlers.append(module_name)
                logger.info(f"✅ Registered router: {module_name}")
            else:
                logger.warning(f"⚠ No registration function found in {module_name}")
                failed_handlers.append(module_name)

        except ImportError:
            logger.warning(f"⚠ Handler {module_name} not found - skipping")
            failed_handlers.append(module_name)
        except Exception as e:
            logger.error(f"❌ Failed to register {module_name}: {e}")
            failed_handlers.append(module_name)

@dp.startup()
async def on_startup():

    logger.info("🚀 TonGPT initialization starting...")

    logger.info(f"🌐 Starting Mini-App server on {MINIAPP_HOST}:{MINIAPP_PORT}...")
    api_thread = threading.Thread(target=start_miniapp_server, daemon=True)
    api_thread.start()

    await initialize_gpt_handler()

    X_initialized = await initialize_X_monitor()

    await register_all_handlers()

    await test_connections_on_startup()

    if X_initialized:
        await start_X_monitoring()

    try:
        from utils.redis_conn import redis_client

        import time
        redis_client.set("bot_startup_time", int(time.time()))
        redis_client.set("bot_status", "online")
        logger.info("📊 Bot status tracking initialized")
    except:
        logger.warning("⚠ Bot status tracking unavailable")

    logger.info(f"✅ Successfully registered {len(registered_handlers)} handlers: {', '.join(registered_handlers)}")
    if failed_handlers:
        logger.warning(f"⚠ Failed to register {len(failed_handlers)} handlers: {', '.join(failed_handlers)}")

    features_enabled = []
    if PAYMENT_TOKEN:
        features_enabled.append("Telegram Stars Payments")
    if TON_API_KEY:
        features_enabled.append("Enhanced TON API")
    if gpt_handler:
        features_enabled.append("Enhanced AI Conversations")
    if X_monitor:
        features_enabled.append("X Monitoring & Alerts")
    features_enabled.append("Mini-App API")
    features_enabled.extend(registered_handlers)

    logger.info(f"🎯 Enabled features: {', '.join(features_enabled)}")
    logger.info("🤖 TonGPT is now running with enhanced capabilities!")
    logger.info(f"🌐 Mini-App available at: http://{MINIAPP_HOST}:{MINIAPP_PORT}")
    logger.info("📋 Available commands: /help, /scan, /X, /defi, /wallets, /nft, /dev, /mining, /security")

@dp.shutdown()
async def on_shutdown():

    logger.info("🛑 TonGPT is shutting down...")

    try:
        from utils.redis_conn import redis_client
        redis_client.set("bot_status", "offline")
        import time
        redis_client.set("bot_shutdown_time", int(time.time()))
        logger.info("📊 Bot status updated to offline")
    except:
        pass

    try:
        await bot.session.close()
        logger.info("🔐 Bot session closed cleanly")
    except:
        logger.warning("⚠ Error closing bot session")

    logger.info("👋 TonGPT shutdown complete")

@dp.error()
async def error_handler(event, exception):

    logger.error(f"🚨 Unhandled exception: {exception}")

    try:
        if hasattr(event, 'message') and event.message:
            await event.message.reply(
                "⚠️ <b>Oops! Something went wrong</b>\n\n"
                "🔧 Our team has been notified and is working on a fix.\n"
                "Please try again in a few moments.\n\n"
                "💡 <b>Alternative commands:</b>\n"
                "• /help - Get assistance\n"
                "• /scan - Check market data\n"
                "• /X - Social media insights\n"
                "• /defi - DeFi information\n"
                "• /wallets - Wallet guide\n"
                "• /start - Restart interaction"
            )
    except:
        pass

    return True

async def main():

    try:
        logger.info("🎬 TonGPT starting up...")

        try:
            bot_info = await bot.get_me()
            logger.info(f"🤖 Bot authenticated: @{bot_info.username} (ID: {bot_info.id})")
        except Exception as e:
            logger.critical(f"❌ Bot authentication failed: {e}")
            return

        await dp.start_polling(
            bot,
            polling_timeout=10,
            handle_signals=True,
            fast=True,
            allowed_updates=["message", "callback_query", "pre_checkout_query"]
        )

    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user (Ctrl+C)")
    except Exception as e:
        logger.exception(f"🚨 Critical error in main loop: {e}")
        raise
    finally:

        try:
            await bot.session.close()
        except:
            pass

async def health_check():

    health_status = {
        "bot": False,
        "redis": False,
        "ton_api": False,
        "gpt": False,
        "X": False,
        "miniapp_api": True,
        "enhanced_features": bool(gpt_handler),
        "timestamp": asyncio.get_event_loop().time()
    }

    try:
        await bot.get_me()
        health_status["bot"] = True
    except:
        pass

    try:
        from utils.redis_conn import redis_client
        redis_client.ping()
        health_status["redis"] = True
    except:
        pass

    try:
        from services.tonapi import test_ton_api_connection
        status = test_ton_api_connection()
        health_status["ton_api"] = status.get("api_status") == "online"
    except:
        pass

    try:
        if gpt_handler:

            response = await gpt_handler.get_comprehensive_response("test", 0)
            health_status["gpt"] = bool(response)
    except:
        pass

    try:
        if X_monitor:
            client = X_monitor.client
            me = client.get_me()
            health_status["X"] = bool(me.data)
    except:
        pass

    return health_status

if __name__ == "__main__":
    try:

        try:
            import setproctitle
            setproctitle.setproctitle("TonGPT-Bot")
        except ImportError:
            pass

        asyncio.run(main())

    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.exception(f"🚨 TonGPT crashed: {e}")
        exit(1)
    finally:
        logger.info("👋 TonGPT process ended")