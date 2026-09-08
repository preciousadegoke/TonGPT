from aiogram import Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from utils.redis_conn import redis_client
import logging

logger = logging.getLogger(__name__)

MAX_ALERTS = 10


class AlertStates(StatesGroup):
    WaitingForToken = State()
    WaitingForPrice = State()


def _decode(v):
    return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)


def _existing_alerts(user_id: str) -> dict:
    try:
        raw = redis_client.hgetall(f"alerts:{user_id}") or {}
        return {_decode(k): _decode(v) for k, v in raw.items()}
    except Exception as e:  # noqa: BLE001
        logger.warning("alerts read failed for %s: %s", user_id, e)
        return {}


async def _maybe_cancel(message: types.Message, state: FSMContext) -> bool:
    """Let the user bail out of the flow at any step with /cancel or 'cancel'."""
    if (message.text or "").strip().lower() in ("/cancel", "cancel"):
        await state.clear()
        await message.answer("👍 Alert setup cancelled. Use /alerts any time.")
        return True
    return False


async def alerts_start(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    existing = _existing_alerts(user_id)

    intro = ["🔔 <b>Price Alerts</b>\n"]
    if existing:
        intro.append("Your active alerts:")
        for field, target in sorted(existing.items()):
            sym = field.split(":")[0] if ":" in field else field
            intro.append(f"• <b>{sym}</b> at ${target}")
        intro.append("")
    if len(existing) >= MAX_ALERTS:
        intro.append(f"⚠️ You've reached the limit of {MAX_ALERTS} alerts. "
                     "An alert frees up automatically when it fires.")
        await message.answer("\n".join(intro), parse_mode="HTML")
        return

    intro.append("Enter the token symbol to set a new alert (e.g. <b>TON</b> or <b>NOT</b>), "
                 "or type <i>cancel</i> to stop:")
    await message.answer("\n".join(intro), parse_mode="HTML")
    await state.set_state(AlertStates.WaitingForToken)


async def alerts_token(message: types.Message, state: FSMContext):
    if await _maybe_cancel(message, state):
        return
    token = (message.text or "").strip().upper()
    if not token or not token.isalnum() or len(token) > 16:
        await message.answer("🤔 That doesn't look like a token symbol. "
                             "Try something like <b>TON</b> or <b>NOT</b>, or type <i>cancel</i>.",
                             parse_mode="HTML")
        return
    await state.update_data(token=token)
    await message.answer(
        f"👍 <b>{token}</b> it is. Now enter the target price in USD "
        f"(I'll ping you when {token} reaches it):",
        parse_mode="HTML",
    )
    await state.set_state(AlertStates.WaitingForPrice)


async def alerts_price(message: types.Message, state: FSMContext):
    if await _maybe_cancel(message, state):
        return
    try:
        price = float((message.text or "").strip().replace("$", "").replace(",", ""))
        if price <= 0:
            raise ValueError("non-positive")
        user_id = str(message.from_user.id)
        data = await state.get_data()
        token = data.get("token")
        redis_client.hset(f"alerts:{user_id}", f"{token}:price", price)
        await message.answer(
            f"✅ <b>Alert set!</b> I'll notify you when <b>{token}</b> reaches "
            f"<b>${price:g}</b>.\n\n"
            f"💡 Track it live too: <code>/watch {token}</code>",
            parse_mode="HTML",
        )
    except ValueError:
        await message.answer("❌ Please enter a positive number, e.g. <b>2.35</b> — "
                             "or type <i>cancel</i>.", parse_mode="HTML")
        return  # stay in this state so the user can retry
    except Exception as e:
        logger.error(f"Alerts Error: {e}")
        await message.answer("⚠️ Couldn't save the alert right now — please try /alerts again shortly.")
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
