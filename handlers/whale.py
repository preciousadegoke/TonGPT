from aiogram import Dispatcher, types
from aiogram.filters import Command
from services.tonapi import get_large_transactions
from utils.redis_conn import redis_client

async def whale(message: types.Message):
    user_id = str(message.from_user.id)
    is_premium = redis_client.get(f"premium:{user_id}")
    if not is_premium:
        await message.answer("❌ /whale requires Premium. Use /subscribe to upgrade.")
        return

    try:
        transactions = await get_large_transactions(limit=5)
        if not transactions:
            await message.answer("❌ No large transactions found.")
            return
        response = "🐳 Recent Large TON Transactions:\n\n"
        for tx in transactions:
            response += f"• {tx['amount']} TON from {tx['sender']} to {tx['recipient']} at {tx['time']}\n"
        await message.answer(response)
    except Exception as e:
        print(f"Whale Error: {e}")
        await message.answer(f"⚠️ Error fetching whale transactions: {e}")

def register_whale_handlers(dp: Dispatcher):
    @dp.message(Command(commands=["whale"]))
    async def wrapper_whale(message: types.Message):
        await whale(message)