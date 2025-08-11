from aiogram import Router, types
from aiogram.filters import Command
from gpt.engine import ask_gpt
from utils.scanner import scan_memecoins
from services.tonviewer_api import get_token_info_from_tonviewer
from utils.redis_conn import redis_client

router = Router()

# /start
@router.message(Command("start"))
async def start(message: types.Message):
    user = message.from_user
    await message.answer(
        f"👋 Hello {user.first_name}!\n\n"
        "I’m TonGPT, your smart AI analyst for TON. Ask me about memecoins, influencers, whale alerts, farming yields and more.\n\n"
        "Use /ask followed by a question, or /scan to see trending TON tokens.\n\n"
        "🚀 Tip: /subscribe to unlock Pro features.\n"
        "💡 Use /help to see all commands."
    )

# /app — Launch Mini App
@router.message(Command("app"))
async def open_app(message: types.Message):
    webapp_url = "https://tongpt.loca.lt"  # change to your production URL when live
    kb = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🚀 Open TonGPT App", web_app=types.WebAppInfo(url=webapp_url))]
        ],
        resize_keyboard=True
    )
    await message.answer("Tap below to launch TonGPT Web App:", reply_markup=kb)

# /info <contract>
@router.message(Command("info"))
async def info(message: types.Message):
    args = message.get_args().split()
    if not args:
        await message.reply("❌ Usage: /info <contract_address>")
        return
    contract = args[0]
    data = get_token_info_from_tonviewer(contract)
    if not data:
        await message.reply("❌ Token not found or invalid.")
        return
    name = data.get("name", "Unknown")
    symbol = data.get("symbol", "")
    price = data.get("price", "N/A")
    holders = data.get("holders", "N/A")
    await message.reply(
        f"📊 <b>{name} ({symbol})</b>\n"
        f"💰 Price: {price}\n"
        f"👥 Holders: {holders}\n"
        f"🔗 Contract: <code>{contract}</code>",
        parse_mode="HTML"
    )

# /ask <question>
@router.message(Command("ask"))
async def ask(message: types.Message):
    question = message.get_args()
    if not question:
        await message.reply("🧠 Usage: /ask <your question>")
        return
    user_id = message.from_user.id
    prompt = f"{question}"
    reply = await ask_gpt(user_id=user_id, prompt=prompt)
    await message.reply(reply)

# /scan
@router.message(Command("scan"))
async def scan(message: types.Message):
    coins = scan_memecoins()
    if not coins:
        await message.reply("No memecoins found on TON right now.")
        return
    msg = "🔍 <b>Trending TON Memecoins:</b>\n\n"
    for coin in coins:
        msg += f"• {coin['name']} ({coin['symbol']})\n"
        msg += f"  💰 LP: {coin['lp']}, 📈 Vol: {coin['volume']}, 🧠 Hype: {coin['hype']}\n"
        msg += f"  🔗 {coin['link']}\n\n"
    await message.reply(msg, parse_mode="HTML")

# /trending
@router.message(Command("trending"))
async def trending(message: types.Message):
    trending_list = redis_client.get("ton_trending_tokens")
    if not trending_list:
        await message.reply("No trending tokens right now.")
        return
    await message.reply(trending_list.decode())

# /influencer
@router.message(Command("influencer"))
async def influencer(message: types.Message):
    tweets = redis_client.get("latest_influencer_tweets")
    if not tweets:
        await message.reply("No influencer tweets found.")
        return
    await message.reply(tweets.decode())

# /refer
@router.message(Command("refer"))
async def refer(message: types.Message):
    uid = message.from_user.id
    referral_link = f"https://t.me/TonGptt_bot?start={uid}"
    await message.reply(
        f"🎉 Invite your friends and earn rewards!\n"
        f"Here’s your referral link:\n{referral_link}"
    )

# /join
@router.message(Command("join"))
async def join(message: types.Message):
    await message.reply(
        "💬 Join our TON Alpha group: https://t.me/TonAlphaGroup\n"
        "📢 Follow our announcements: https://t.me/TonGPT_Official"
    )

# /subscribe
@router.message(Command("subscribe"))
async def subscribe(message: types.Message):
    await message.reply(
        "💎 <b>TonGPT Pro Plans</b>\n\n"
        "Starter — 0.8 TON\n"
        "Pro — 3 TON\n"
        "Pro+ — 6 TON\n"
        "Elite — 10 TON\n\n"
        "💸 Pay with TON via @TonGptt_bot or use /pay\n"
        "🎁 Use /refer to invite and earn access.\n",
        parse_mode="HTML"
    )

# Payments
@router.pre_checkout_query()
async def pre_checkout_callback(pre_checkout_query: types.PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@router.message(lambda msg: msg.content_type == types.ContentType.SUCCESSFUL_PAYMENT)
async def successful_payment(message: types.Message):
    await message.reply("✅ Payment received! Your access has been upgraded.")

# Final registration
def register_commands(dp, config: dict):
    dp.include_router(router)
