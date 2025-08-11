from aiogram import Dispatcher, types
from aiogram.filters import Command
from services.stonfi_api import fetch_top_ston_pools

async def handle_ston_command(message: types.Message):
    await message.answer("Fetching top STON.fi pools...")

    try:
        pools = await fetch_top_ston_pools()
        if not pools:
            await message.answer("❌ No pools found.")
            return

        for pool in pools:
            msg = (
                f"🏦 <b>{pool['token0']}/{pool['token1']}</b>\n"
                f"💧 TVL: ${pool['tvl_usd']:,}\n"
                f"📈 APR: {pool['apr']}%\n"
                f"🔗 <a href='{pool['link']}'>View on STON.fi</a>"
            )
            await message.answer(msg, parse_mode="HTML")

    except Exception as e:
        print(f"STON Error: {e}")
        await message.answer(f"⚠️ Error fetching data: {e}")

def register_ston_handlers(dp: Dispatcher):
    @dp.message(Command(commands=["ston"]))
    async def wrapper_ston(message: types.Message):
        await handle_ston_command(message)