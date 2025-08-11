from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import redis
import os
from dotenv import load_dotenv
from services.stonfi_api import fetch_top_ston_pools
from services.tonapi import get_transactions
from utils.scanner import scan_memecoins
from utils.redis_conn import redis_client
from datetime import datetime, timedelta

app = FastAPI()
app.mount("/miniapp", StaticFiles(directory="miniapp"), name="miniapp")

load_dotenv()
REDIS_HOST = os.getenv("REDIS_HOST", "redis-15513.c93.us-east-1-3.ec2.redns.redis-cloud.com")
REDIS_PORT = int(os.getenv("REDIS_PORT", 15513))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

@app.get("/")
async def serve_miniapp():
    return FileResponse("miniapp/index.html")

@app.get("/api/scan")
async def get_trending_coins():
    try:
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/whale")
async def get_whale_transactions():
    try:
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/ston")
async def get_ston_pools():
    try:
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
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/alerts/{user_id}")
async def get_user_alerts(user_id: str):
    try:
        alerts = redis_client.hgetall(f"alerts:{user_id}")
        return [
            {
                "token": key.split(":")[0],
                "condition": f"Price > ${value}",
                "status": "active" if redis_client.get(f"alerts:{user_id}:{key}:status") == "active" else "pending"
            } for key, value in alerts.items()
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/follow/{user_id}")
async def get_followed_wallets(user_id: str):
    try:
        wallets = redis_client.smembers(f"follows:{user_id}")
        return [
            {
                "address": wallet,
                "label": f"Wallet {i+1}",
                "lastTx": "Unknown",
                "time": (datetime.now() - timedelta(hours=i)).strftime("%H:%M:%S")
            } for i, wallet in enumerate(wallets)
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats/{user_id}")
async def get_user_stats(user_id: str):
    try:
        referrals = int(redis_client.get(f"referral_count:{user_id}") or 0)
        return {
            "referrals": referrals,
            "earned": f"{referrals * 3} TON",
            "activeAlerts": len(redis_client.hgetall(f"alerts:{user_id}")),
            "followedWallets": len(redis_client.smembers(f"follows:{user_id}"))
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/wallet/connect")
async def connect_wallet(data: dict):
    user_id = data.get("userId")
    address = data.get("address")
    try:
        redis_client.set(f"wallet:{user_id}", address)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/wallet/disconnect")
async def disconnect_wallet(data: dict):
    user_id = data.get("userId")
    try:
        redis_client.delete(f"wallet:{user_id}")
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))