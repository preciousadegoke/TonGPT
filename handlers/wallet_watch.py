from aiogram import Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from services.tonapi import get_wallet_transactions
from utils.redis_conn import redis_client

class WalletWatchStates(StatesGroup):
    WaitingForAddress = State()

async def wallet_watch_start(message: types.Message, state: FSMContext):
    await message.answer("Enter the TON wallet address to watch:")
    await state.set_state(WalletWatchStates.WaitingForAddress)

async def wallet_watch_address(message: types.Message, state: FSMContext):
    address = message.text.strip()
    user_id = str(message.from_user.id)
    redis_client.sadd(f"wallets:{user_id}", address)
    await message.answer(f"Added {address} to watchlist. Tracking transactions...")
    try:
        transactions = await get_wallet_transactions(address, limit=5)
        if not transactions:
            await message.answer("No recent transactions found.")
            return
        response = f"Recent transactions for {address}:\n"
        for tx in transactions:
            response += f"• {tx['type']}: {tx['amount']} TON at {tx['time']}\n"
        await message.answer(response)
    except Exception as e:
        print(f"Wallet Watch Error: {e}")
        await message.answer(f"⚠️ Error fetching transactions: {e}")
    await state.clear()

def register_wallet_handlers(dp: Dispatcher):
    @dp.message(Command(commands=["wallet_watch"]))
    async def wrapper_wallet_watch(message: types.Message, state: FSMContext):
        await wallet_watch_start(message, state)
    
    @dp.message(WalletWatchStates.WaitingForAddress)
    async def wrapper_wallet_address(message: types.Message, state: FSMContext):
        await wallet_watch_address(message, state)