# handlers/influencer_handler.py - FIXED for aiogram 3.x (C-12)
from aiogram import Router, types
from aiogram.filters import Command
from utils.redis_conn import redis_client
import logging

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("influencer", "influencers"))
async def influencer(message: types.Message):
    user_id = str(message.from_user.id)

    try:
        from services.tweet_sentiment import analyze_tweets
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
        if redis_client:
            try:
                redis_client.zadd("command_usage", {user_id: 1})
            except Exception:
                pass
        await message.answer(response, parse_mode="HTML")

    except ImportError:
        logger.warning("tweet_sentiment module not available")
        await message.answer("⚠️ Influencer tracking is currently unavailable.")
    except Exception as e:
        logger.error(f"Influencer command failed: {e}")
        await message.answer("⚠️ Error fetching influencer posts. Please try again later.")


def register_influencer_handlers(dp, ctx=None):
    """Register influencer handlers with the dispatcher"""
    dp.include_router(router)