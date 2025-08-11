from aiogram import Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from utils.redis_conn import redis_client

class AlertStates(StatesGroup):
    WaitingForToken = State()
    WaitingForPrice = State()

async def alerts_start(message: types.Message, state: FSMContext):
    await message.answer("Enter the token symbol for price alerts (e.g., TON):")
    await state.set_state(AlertStates.WaitingForToken)

async def alerts_token(message: types.Message, state: FSMContext):
    token = message.text.strip().upper()
    await state.update_data(token=token)
    await message.answer(f"Set alert for {token}. Enter target price (USD):")
    await state.set_state(AlertStates.WaitingForPrice)

async def alerts_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text.strip())
        user_id = str(message.from_user.id)
        data = await state.get_data()
        token = data.get("token")
        redis_client.hset(f"alerts:{user_id}", f"{token}:price", price)
        await message.answer(f"Alert set for {token} at ${price}.")
    except ValueError:
        await message.answer("❌ Please enter a valid number for the price.")
    except Exception as e:
        print(f"Alerts Error: {e}")
        await message.answer(f"⚠️ Error setting alert: {e}")
    await state.clear()

def register_alerts_handlers(dp: Dispatcher):
    @dp.message(Command(commands=["alerts"]))
    async def wrapper_alerts(message: types.Message, state: FSMContext):
        await alerts_start(message, state)
    
    @dp.message(AlertStates.WaitingForToken)
    async def wrapper_token(message: types.Message, state: FSMContext):
        await alerts_token(message, state)
    
    @dp.message(AlertStates.WaitingForPrice)
    async def wrapper_price(message: types.Message, state: FSMContext):
        await alerts_price(message, state)