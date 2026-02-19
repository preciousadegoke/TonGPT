"""
FastAPI server for TonGPT Mini-App
"""
from datetime import datetime, timedelta
from typing import Dict, Any
import logging

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from services.analysis import analyze_token_ai, analyze_wallet_ai, calculate_risk_score, process_sentiment_data

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan for FastAPI mini-app"""
    logger.info("🚀 Starting Mini-App API server...")
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

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, specify your domain
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files for the mini-app
    app.mount("/miniapp", StaticFiles(directory="miniapp"), name="miniapp")
    
    return app

# Create the app instance
miniapp = create_miniapp_server()

# ==================== MINI-APP API ROUTES ====================

@miniapp.get("/")
async def serve_miniapp():
    """Serve the mini-app HTML"""
    return FileResponse("miniapp/index.html")

@miniapp.get("/api/scan")
async def get_trending_coins():
    """Get trending coins for the mini-app"""
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
        # Return mock data for testing
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
async def scan_token(data: dict):
    """Scan token contract for detailed information"""
    try:
        contract_address = data.get('address')
        
        if not contract_address:
            raise HTTPException(status_code=400, detail="Contract address is required")
        
        # Get token analysis
        analysis = analyze_token_ai(contract_address)
        
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
async def get_ai_analysis(data: dict):
    """Get AI-powered analysis for tokens or wallets"""
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
async def get_user_status(telegram_id: int):
    """Get user subscription status from C# Engine"""
    try:
        from services.engine_client import EngineClient
        # Initialize client (base_url is loaded from env inside class)
        client = EngineClient() 
        user = await client.get_user(telegram_id)
        
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
    except:
        # Fallback Mock
        return [
            {"name": "DOGCOIN", "symbol": "DOG", "price": "$0.0045", "change": "+12.5%", "lp": "1,250,000", "holders": "8,500", "age": "2d", "volume": "750,000"},
            {"name": "CATCOIN", "symbol": "CAT", "price": "$0.0032", "change": "-3.2%", "lp": "980,000", "holders": "6,200", "age": "5d", "volume": "420,000"}
        ]

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
    except:
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
    except:
        return {"sentiment": "neutral", "posts": [], "summary": "Data unavailable"}