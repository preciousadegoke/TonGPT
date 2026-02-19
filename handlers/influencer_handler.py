from aiogram import Dispatcher, types
from aiogram.filters import Command
from services.tweet_sentiment import analyze_tweets
from utils.redis_conn import redis_client
import logging

logger = logging.getLogger(__name__)

async def influencer(message: types.Message):
    user_id = str(message.from_user.id)
    
    try:
        posts = analyze_tweets()
        
        if not posts:
            await message.answer("📊 No recent influencer posts found. Try again later!")
            return
        
        response = "🐦 <b>TON Influencer Buzz</b> 🔥\n\n"
        
        for i, post in enumerate(posts[:5], 1):
            verified = "✅ " if post.get('verified') else ""
            response += f"{i}. {verified}<b>@{post['user']}</b> ({post['followers']:,} followers)\n"
            response += f"   {post['text']}\n"
            response += f"   📈 Sentiment: <b>{post['sentiment']}</b>\n"
            response += f"   ❤️ {post.get('likes', 0)} | 🔄 {post.get('retweets', 0)}\n\n"
        
        # Track usage
        redis_client.zincrby("command_usage", 1, user_id)
        await message.answer(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Influencer command failed: {e}")
        await message.answer("⚠️ Error fetching influencer posts. Please try again later.")

def register_influencer_handlers(dp: Dispatcher):
    dp.register_message_handler(influencer, Command(commands=["influencer", "influencers"]))