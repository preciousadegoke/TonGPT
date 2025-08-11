from aiogram import Dispatcher, types
from aiogram.filters import Command
from utils.scanner import scan_memecoins

async def scan(message: types.Message):
    try:
        tokens = await scan_memecoins(limit=10)
        if not tokens:
            return await message.answer("❌ Couldn't fetch memecoin list right now.")

        reply = "<b>🔥 Top TON Memecoins Today:</b>\n\n"
        reply += "\n".join(
            [f"• ${t['symbol']} — {t['change']}% | ${t['price']}" for t in tokens]
        )
        await message.answer(reply, parse_mode="HTML")
    except Exception as e:
        print(f"[ERROR] /scan failed: {e}")
        await message.answer("⚠️ Error fetching scan results.")

def register_scan_handlers(dp: Dispatcher):
    @dp.message(Command(commands=["scan"]))
    async def wrapper_scan(message: types.Message):
        await scan(message)