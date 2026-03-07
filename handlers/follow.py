from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from utils.redis_conn import redis_client
from services.engine_client import engine_client
from handlers.whale import get_user_premium_status
import logging

logger = logging.getLogger(__name__)
router = Router()


class FollowStates(StatesGroup):
    WaitingForAddress = State()


@router.message(Command("follow"))
async def follow_start(message: types.Message, state: FSMContext):
    """Start following a wallet address"""
    await message.answer(
        "📋 <b>Enter TON wallet address to follow:</b>\n\nExample: <code>EQABC...xyz</code>",
        parse_mode="HTML",
    )
    await state.set_state(FollowStates.WaitingForAddress)


@router.message(FollowStates.WaitingForAddress)
async def follow_address(message: types.Message, state: FSMContext):
    address = message.text.strip()
    user_id = message.from_user.id
    
    # Basic validation
    if not address.startswith(("EQ", "UQ", "0:")):
        await message.answer("❌ Invalid TON address format. Must start with EQ, UQ, or 0:")
        return
    
    # Check premium status via Engine with Redis cache
    has_premium = await get_user_premium_status(redis_client, engine_client, user_id)
    if not has_premium:
        await message.answer(
            "❌ <b>Premium Feature</b>\n\nUse /subscribe to unlock wallet tracking with real-time alerts!",
            parse_mode="HTML",
        )
        await state.clear()
        return
    
    user_key = str(user_id)
    # Add to followed addresses
    redis_client.sadd(f"follows:{user_key}", address)
    
    # Track this address for alerts
    redis_client.sadd("tracked_addresses", address)
    
    await message.answer(
        f"✅ <b>Now following:</b> <code>{address[:12]}...{address[-6:]}</code>\n\nYou'll receive alerts for large transactions!",
        parse_mode="HTML",
    )
    await state.clear()


@router.message(Command("unfollow", "following"))
async def unfollow(message: types.Message):
    """Stop following addresses"""
    user_key = str(message.from_user.id)
    addresses = redis_client.smembers(f"follows:{user_key}")
    
    if not addresses:
        await message.answer("❌ You're not following any addresses.")
        return
    
    response = "📋 <b>Your followed addresses:</b>\n\n"
    for i, addr in enumerate(addresses, 1):
        addr_str = addr.decode() if isinstance(addr, bytes) else str(addr)
        response += f"{i}. <code>{addr_str[:12]}...{addr_str[-6:]}</code>\n"
    
    response += "\nReply with /unfollow <number> to stop following."
    await message.answer(response, parse_mode="HTML")


def register_follow_handlers(dp):
    dp.include_router(router)