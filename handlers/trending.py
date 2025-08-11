from aiogram import Dispatcher, types
from aiogram.filters import Command
from utils.scanner import scan_memecoins
from gpt.engine import ask_gpt

async def trending(message: types.Message):
    try:
        tokens = await scan_memecoins(limit=7)
        if not tokens:
            return await message.answer("❌ Couldn't fetch trending token data.")

        context = "Top TON Meme Tokens by Volume:\n"
        context += "\n".join(
            [f"• ${t['symbol']} | {t['change']}% | ${t['price']}" for t in tokens]
        )

        prompt = (
            f"{context}\n\n"
            "Based on volume and price changes, what memecoins are most promising? "
            "Consider hype, volatility, and Twitter buzz. Return insights in a crypto-native tone (not financial advice)."
        )

        await message.bot.send_chat_action(message.chat.id, "typing")
        reply = await ask_gpt(prompt)
        await message.answer(reply)
    except Exception as e:
        print(f"[ERROR] /trending failed: {e}")
        await message.answer("⚠️ Error fetching GPT insights.")

def register_trending_handlers(dp: Dispatcher):
    @dp.message(Command(commands=["trending"]))
    async def wrapper_trending(message: types.Message):
        await trending(message)