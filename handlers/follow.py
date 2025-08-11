from aiogram import Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from utils.redis_conn import redis_client

class FollowStates(StatesGroup):
    WaitingForAddress = State()

async def follow_start(message: types.Message, state: FSMContext):
    await message.answer("Enter the TON wallet or contract address to follow:")
    await state.set_state(FollowStates.WaitingForAddress)

async def follow_address(message: types.Message, state: FSMContext):
    address = message.text.strip()
    user_id = str(message.from_user.id)
    is_premium = redis_client.get(f"premium:{user_id}")
    if not is_premium:
        await message.answer("❌ /follow requires Premium. Use /subscribe to upgrade.")
        await state.clear()
        return
    redis_client.sadd(f"follows:{user_id}", address)
    await message.answer(f"Following {address}. You'll receive updates on activity.")
    await state.clear()

def register_follow_handlers(dp: Dispatcher):
    @dp.message(Command(commands=["follow"]))
    async def wrapper_follow(message: types.Message, state: FSMContext):
        await follow_start(message, state)
    
    @dp.message(FollowStates.WaitingForAddress)
    async def wrapper_address(message: types.Message, state: FSMContext):
        await follow_address(message, state)