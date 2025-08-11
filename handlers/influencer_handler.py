from aiogram import Dispatcher, types
from aiogram.filters import Command
from services.tweet_sentiment import analyze_tweets
from utils.redis_conn import redis_client

async def influencer(message: types.Message):
    user_id = str(message.from_user.id)
    is_premium = redis_client.get(f"premium:{user_id}")
    if not is_premium:
        await message.answer("Basic /influencer (upgrade with /subscribe for real-time alerts):\nTracking limited to cached posts.")
        return

    try:
        posts = await analyze_tweets()
        response = "🔥 TON Influencer Buzz 🔥\n\n"
        for post in posts[:3]:
            response += f"👤 @{post['user']} ({post['followers']} followers):\n"
            response += f"💬 {post['text']}\n"
            response += f"😊 Sentiment: {post['sentiment']}\n\n"
        response += "Invite friends with /refer to unlock Premium for free!"
        redis_client.zincrby("command_usage", 1, user_id)
        await message.answer(response)
    except Exception as e:
        print(f"[ERROR] /influencer failed: {e}")
        await message.answer("⚠️ Error fetching influencer posts.")

def register_influencer_handlers(dp: Dispatcher):
    @dp.message(Command(commands=["influencer"]))
    async def wrapper_influencer(message: types.Message):
        await influencer(message)