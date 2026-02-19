from aiogram import Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from utils.redis_conn import redis_client
import logging

logger = logging.getLogger(__name__)

class FollowStates(StatesGroup):
    WaitingForAddress = State()

async def follow_start(message: types.Message, state: FSMContext):
    """Start following a wallet address"""
    await message.answer("📋 <b>Enter TON wallet address to follow:</b>\n\nExample: <code>EQABC...xyz</code>", parse_mode="HTML")
    await state.set_state(FollowStates.WaitingForAddress)

async def follow_address(message: types.Message, state: FSMContext):
    address = message.text.strip()
    user_id = str(message.from_user.id)
    
    # Basic validation
    if not address.startswith(('EQ', 'UQ', '0:')):
        await message.answer("❌ Invalid TON address format. Must start with EQ, UQ, or 0:")
        return
    
    # Check premium status
    is_premium = redis_client.get(f"premium:{user_id}")
    if not is_premium:
        await message.answer("❌ <b>Premium Feature</b>\n\nUse /subscribe to unlock wallet tracking with real-time alerts!", parse_mode="HTML")
        await state.clear()
        return
    
    # Add to followed addresses
    redis_client.sadd(f"follows:{user_id}", address)
    
    # Track this address for alerts
    redis_client.sadd("tracked_addresses", address)
    
    await message.answer(f"✅ <b>Now following:</b> <code>{address[:12]}...{address[-6:]}</code>\n\nYou'll receive alerts for large transactions!", parse_mode="HTML")
    await state.clear()

async def unfollow(message: types.Message):
    """Stop following addresses"""
    user_id = str(message.from_user.id)
    addresses = redis_client.smembers(f"follows:{user_id}")
    
    if not addresses:
        await message.answer("❌ You're not following any addresses.")
        return
    
    response = "📋 <b>Your followed addresses:</b>\n\n"
    for i, addr in enumerate(addresses, 1):
        response += f"{i}. <code>{addr.decode()[:12]}...{addr.decode()[-6:]}</code>\n"
    
    response += "\nReply with /unfollow <number> to stop following."
    await message.answer(response, parse_mode="HTML")

def register_follow_handlers(dp: Dispatcher):
    dp.register_message_handler(follow_start, Command(commands=["follow"]))
    dp.register_message_handler(unfollow, Command(commands=["unfollow", "following"]))
    dp.register_message_handler(follow_address, state=FollowStates.WaitingForAddress)