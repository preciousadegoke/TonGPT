from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from utils.redis_conn import redis_client
from services.engine_client import engine_client
import logging
import json
from datetime import datetime, timedelta
import sqlite3

logger = logging.getLogger(__name__)

class XStates(StatesGroup):
    WaitingForUsername = State()
    WaitingForKeyword = State()

# Create router
router = Router()

@router.message(Command("X"))
async def X_menu(message: types.Message):
    """Main X monitoring dashboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐦 Influencer Posts", callback_data="X_influencer")],
        [InlineKeyboardButton(text="📈 TON Sentiment", callback_data="X_sentiment")],
        [InlineKeyboardButton(text="📊 X Stats", callback_data="X_stats")],
        [InlineKeyboardButton(text="⚡ Recent Alerts", callback_data="X_alerts")],
        [InlineKeyboardButton(text="🔍 Monitor Keywords", callback_data="X_monitor")]
    ])
    
    await message.answer(
        "🐦 <b>X Monitor Dashboard</b>\n\n"
        "Track TON mentions, analyze influencer posts, and monitor market sentiment from X.\n\n"
        "Choose an option below:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@router.callback_query(lambda c: c.data.startswith("X_"))
async def handle_X_callbacks(callback: CallbackQuery):
    """Handle all X-related callback queries"""
    action = callback.data
    
    try:
        if action == "X_influencer":
            await show_influencer_posts(callback)
        elif action == "X_sentiment":
            await show_sentiment_analysis(callback)
        elif action == "X_stats":
            await show_X_stats(callback)
        elif action == "X_alerts":
            await show_recent_alerts(callback)
        elif action == "X_monitor":
            await setup_keyword_monitoring(callback)
        elif action == "back_to_X_menu":
            await back_to_X_menu(callback)
    except Exception as e:
        logger.error(f"X callback error: {e}")
        await callback.message.edit_text("⚠️ Error processing request. Please try again.")
    
    await callback.answer()

async def show_influencer_posts(callback: CallbackQuery):
    """Display recent influencer posts about TON"""
    try:
        # Try to get live influencer data
        from services.tweet_sentiment import analyze_tweets
        posts = analyze_tweets()
        
        if not posts:
            await callback.message.edit_text(
                "📊 <b>No Recent Influencer Posts</b>\n\n"
                "The system monitors major crypto influencers for TON mentions:\n"
                "• @elonmusk • @VitalikButerin • @CZ_Binance\n"
                "• @APompliano • @saylor • @starkness\n\n"
                "Check back in a few minutes for updates!",
                reply_markup=get_back_button(),
                parse_mode="HTML"
            )
            return
        
        response = "🐦 <b>TON Influencer Activity</b> 🔥\n\n"
        
        for i, post in enumerate(posts[:5], 1):
            verified = "✅ " if post.get('verified') else ""
            sentiment_emoji = get_sentiment_emoji(post['sentiment'])
            
            response += f"{i}. {verified}<b>@{post['user']}</b>\n"
            response += f"   👥 {post['followers']:,} followers\n"
            response += f"   💬 {post['text'][:120]}{'...' if len(post['text']) > 120 else ''}\n"
            response += f"   {sentiment_emoji} <b>{post['sentiment'].title()}</b>\n"
            response += f"   ❤️ {post.get('likes', 0)} | 🔄 {post.get('retweets', 0)}\n\n"
        
        response += "⏰ <i>Updated every 5 minutes</i>"
        
        await callback.message.edit_text(
            response, 
            reply_markup=get_back_button(), 
            parse_mode="HTML"
        )
        
    except ImportError:
        await callback.message.edit_text(
            "⚠️ <b>X Service Unavailable</b>\n\n"
            "The influencer monitoring service is currently offline.\n\n"
            "Features include:\n"
            "• Real-time influencer tracking\n"
            "• Sentiment analysis\n"
            "• Engagement metrics\n"
            "• Premium user alerts\n\n"
            "Please check back later!",
            reply_markup=get_back_button(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error showing influencer posts: {e}")
        await callback.message.edit_text(
            "⚠️ Error fetching influencer posts. Please try again later.",
            reply_markup=get_back_button()
        )

async def show_sentiment_analysis(callback: CallbackQuery):
    """Show comprehensive X sentiment analysis"""
    try:
        # Get recent tweets from database if available
        conn = None
        tweets = []
        
        try:
            conn = sqlite3.connect('ton_tweets.db')
            cursor = conn.cursor()
            
            # Get tweets from last 24 hours
            yesterday = datetime.utcnow() - timedelta(hours=24)
            cursor.execute('''
                SELECT sentiment_score, retweet_count, like_count, username, content, is_influencer
                FROM tweets 
                WHERE is_ton_related = 1 AND created_at > ?
                ORDER BY created_at DESC
                LIMIT 100
            ''', (yesterday,))
            
            tweets = cursor.fetchall()
            
        except Exception as db_error:
            logger.error(f"Database query failed: {db_error}")
        finally:
            if conn:
                conn.close()
        
        if not tweets:
            await callback.message.edit_text(
                "📊 <b>X Sentiment Analysis</b>\n\n"
                "🔧 <b>System Status:</b> Initializing\n\n"
                "This dashboard will show:\n"
                "• Overall TON sentiment (24h)\n"
                "• Bullish vs Bearish breakdown\n"
                "• Influencer vs Community sentiment\n"
                "• Tweet volume trends\n"
                "• Sentiment score distribution\n\n"
                "⏰ Check back in 10-15 minutes for data!",
                reply_markup=get_back_button(),
                parse_mode="HTML"
            )
            return
        
        # Calculate sentiment metrics
        sentiment_scores = [tweet[0] for tweet in tweets if tweet[0] is not None]
        avg_sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0
        
        bullish_count = len([s for s in sentiment_scores if s > 0.1])
        bearish_count = len([s for s in sentiment_scores if s < -0.1])
        neutral_count = len(sentiment_scores) - bullish_count - bearish_count
        
        influencer_tweets = [t for t in tweets if t[5]]  # is_influencer column
        community_tweets = [t for t in tweets if not t[5]]
        
        # Determine overall mood
        if avg_sentiment > 0.1:
            mood = "Bullish 📈"
            mood_emoji = "🟢"
        elif avg_sentiment < -0.1:
            mood = "Bearish 📉"
            mood_emoji = "🔴"
        else:
            mood = "Neutral ➡️"
            mood_emoji = "🟡"
        
        response = f"📊 <b>TON X Sentiment (24h)</b>\n\n"
        response += f"{mood_emoji} <b>Overall Mood: {mood}</b>\n"
        response += f"📈 Sentiment Score: {avg_sentiment:.2f}/1.0\n\n"
        
        response += f"📊 <b>Breakdown ({len(tweets)} tweets):</b>\n"
        response += f"🟢 Bullish: {bullish_count} tweets ({bullish_count/len(tweets)*100:.0f}%)\n"
        response += f"🔴 Bearish: {bearish_count} tweets ({bearish_count/len(tweets)*100:.0f}%)\n"
        response += f"🟡 Neutral: {neutral_count} tweets ({neutral_count/len(tweets)*100:.0f}%)\n\n"
        
        response += f"⭐ <b>Source Breakdown:</b>\n"
        response += f"👑 Influencers: {len(influencer_tweets)} tweets\n"
        response += f"👥 Community: {len(community_tweets)} tweets\n\n"
        
        # Top engagement
        top_engagement = sorted(tweets, key=lambda x: (x[1] or 0) + (x[2] or 0), reverse=True)[:3]
        if top_engagement:
            response += f"🔥 <b>Top Engagement:</b>\n"
            for i, tweet in enumerate(top_engagement, 1):
                username = tweet[3] if tweet[3] else "Unknown"
                content = tweet[4][:60] + "..." if len(tweet[4]) > 60 else tweet[4]
                total_engagement = (tweet[1] or 0) + (tweet[2] or 0)
                response += f"{i}. @{username}: {content}\n"
                response += f"   📊 {total_engagement:,} total interactions\n"
        
        response += f"\n⏰ <i>Last updated: {datetime.now().strftime('%H:%M UTC')}</i>"
        
        await callback.message.edit_text(
            response, 
            reply_markup=get_back_button(), 
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Error showing sentiment analysis: {e}")
        await callback.message.edit_text(
            "📊 <b>X Sentiment</b>\n\n"
            "⚠️ Unable to load sentiment data.\n\n"
            "This could be due to:\n"
            "• Database initialization in progress\n"
            "• X API rate limits\n"
            "• System maintenance\n\n"
            "Please try again in a few minutes.",
            reply_markup=get_back_button(),
            parse_mode="HTML"
        )

async def show_X_stats(callback: CallbackQuery):
    """Show comprehensive X monitoring statistics"""
    try:
        stats = {}
        
        # Try to get stats from database
        try:
            conn = sqlite3.connect('ton_tweets.db')
            cursor = conn.cursor()
            
            # Total tweets tracked
            cursor.execute("SELECT COUNT(*) FROM tweets WHERE is_ton_related = 1")
            stats['total_tweets'] = cursor.fetchone()[0]
            
            # Influencer tweets
            cursor.execute("SELECT COUNT(*) FROM tweets WHERE is_influencer = 1 AND is_ton_related = 1")
            stats['influencer_tweets'] = cursor.fetchone()[0]
            
            # Average engagement
            cursor.execute('''
                SELECT AVG(retweet_count), AVG(like_count) 
                FROM tweets WHERE is_ton_related = 1 AND retweet_count IS NOT NULL
            ''')
            avg_engagement = cursor.fetchone()
            stats['avg_retweets'] = avg_engagement[0] if avg_engagement[0] else 0
            stats['avg_likes'] = avg_engagement[1] if avg_engagement[1] else 0
            
            # Recent activity (last 24h)
            yesterday = datetime.utcnow() - timedelta(hours=24)
            cursor.execute('''
                SELECT COUNT(*) FROM tweets 
                WHERE is_ton_related = 1 AND created_at > ?
            ''', (yesterday,))
            stats['recent_tweets'] = cursor.fetchone()[0]
            
            # Last check time
            cursor.execute("SELECT value FROM monitoring_state WHERE key = 'last_check'")
            last_check_result = cursor.fetchone()
            stats['last_check'] = last_check_result[0] if last_check_result else None
            
            conn.close()
            
        except Exception as db_error:
            logger.error(f"Database stats query failed: {db_error}")
            stats = {}
        
        if not stats:
            # Fallback stats display
            await callback.message.edit_text(
                "📊 <b>X Monitor Statistics</b>\n\n"
                "🔧 <b>System Status:</b> Initializing\n\n"
                "📈 <b>Tracking Capabilities:</b>\n"
                "• TON-related keyword monitoring\n"
                "• Major influencer tracking (12+ accounts)\n"
                "• Real-time sentiment analysis\n"
                "• Engagement metrics collection\n"
                "• Alert system for premium users\n\n"
                "🕐 <b>Update Frequency:</b>\n"
                "• Checks every 5 minutes\n"
                "• Processes 100+ tweets per cycle\n"
                "• Tracks 15+ TON keywords\n\n"
                "⏰ Stats will be available after first monitoring cycle completes!",
                reply_markup=get_back_button(),
                parse_mode="HTML"
            )
            return
        
        response = "📊 <b>X Monitor Statistics</b>\n\n"
        response += f"🐦 <b>Total TON tweets tracked:</b> {stats['total_tweets']:,}\n"
        response += f"⭐ <b>Influencer tweets:</b> {stats['influencer_tweets']:,}\n"
        response += f"📅 <b>Recent activity (24h):</b> {stats['recent_tweets']:,}\n\n"
        
        response += f"📊 <b>Engagement Averages:</b>\n"
        response += f"🔄 Retweets: {stats['avg_retweets']:.1f}\n"
        response += f"❤️ Likes: {stats['avg_likes']:.1f}\n\n"
        
        if stats['last_check']:
            try:
                last_time = datetime.fromisoformat(stats['last_check'])
                time_diff = datetime.utcnow() - last_time
                minutes_ago = int(time_diff.total_seconds() / 60)
                response += f"🕐 <b>Last check:</b> {minutes_ago} minutes ago\n"
            except:
                response += f"🕐 <b>Last check:</b> Recently\n"
        
        response += f"\n⚙️ <b>System Info:</b>\n"
        response += f"🔄 Checks every 5 minutes\n"
        response += f"🎯 Monitors 15+ TON keywords\n"
        response += f"👥 Tracks 12+ major influencers\n"
        response += f"🤖 AI sentiment analysis enabled\n\n"
        
        # Get Redis stats if available
        try:
            alert_count = redis_client.llen("X_alerts")
            response += f"🚨 <b>Alerts generated:</b> {alert_count}\n"
        except:
            pass
        
        response += f"\n💡 <i>Use /subscribe for premium X alerts!</i>"
        
        await callback.message.edit_text(
            response, 
            reply_markup=get_back_button(), 
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Error showing X stats: {e}")
        await callback.message.edit_text(
            "⚠️ Error loading statistics. Please try again later.",
            reply_markup=get_back_button()
        )

async def show_recent_alerts(callback: CallbackQuery):
    """Show recent X alerts"""
    try:
        alerts = []
        
        # Get recent alerts from Redis
        try:
            alert_data = redis_client.lrange("X_alerts", 0, 9)  # Last 10 alerts
            alerts = [json.loads(alert.decode()) for alert in alert_data]
        except Exception as redis_error:
            logger.error(f"Redis alerts fetch failed: {redis_error}")
        
        if not alerts:
            response = "🔔 <b>X Alert System</b>\n\n"
            response += "📊 <b>Status:</b> No recent alerts\n\n"
            response += "🚨 <b>Alert Triggers:</b>\n"
            response += "• Major influencer TON mentions\n"
            response += "• Viral tweets (1000+ interactions)\n"
            response += "• Significant sentiment shifts\n"
            response += "• Breaking TON news\n\n"
            response += "⭐ <b>Premium Features:</b>\n"
            response += "• Instant alert notifications\n"
            response += "• Custom keyword monitoring\n"
            response += "• Sentiment threshold alerts\n\n"
            response += "💡 <i>Use /subscribe to enable alerts!</i>"
        else:
            response = "🔔 <b>Recent X Alerts</b>\n\n"
            for i, alert in enumerate(alerts[:7], 1):  # Show max 7 alerts
                username = alert.get('username', 'Unknown')
                text = alert.get('text', 'No content')
                timestamp = alert.get('timestamp', 'Unknown time')
                
                response += f"{i}. 🚨 <b>@{username}</b>\n"
                response += f"   💬 {text}...\n"
                response += f"   🕐 {timestamp}\n\n"
            
            response += f"📊 <b>Total alerts:</b> {len(alerts)}\n"
            response += "⏰ <i>Alerts are generated in real-time</i>"
        
        await callback.message.edit_text(
            response, 
            reply_markup=get_back_button(), 
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Error showing alerts: {e}")
        await callback.message.edit_text(
            "⚠️ Error loading alerts. Please try again later.",
            reply_markup=get_back_button()
        )

async def setup_keyword_monitoring(callback: CallbackQuery):
    """Setup custom keyword monitoring (premium feature)"""
    user_id = callback.from_user.id
    
    # Check premium status via Engine with Redis cache
    from handlers.whale import get_user_premium_status
    has_premium = await get_user_premium_status(redis_client, engine_client, user_id)
    if not has_premium:
        await callback.message.edit_text(
            "🔍 <b>Custom Keyword Monitoring</b>\n\n"
            "❌ <b>Premium Feature Required</b>\n\n"
            "This feature allows you to:\n"
            "• Monitor custom keywords\n"
            "• Set up personalized alerts\n"
            "• Track specific topics\n"
            "• Get priority notifications\n\n"
            "💎 <b>Upgrade to Premium:</b>\n"
            "Use /subscribe to unlock this and other Pro features!\n\n"
            "🎁 <b>Free Alternative:</b>\n"
            "Use /ask to search for specific topics manually.",
            reply_markup=get_back_button(),
            parse_mode="HTML"
        )
        return
    
    await callback.message.edit_text(
        "🔍 <b>Custom Keyword Monitoring</b>\n\n"
        "🔧 <b>Feature Status:</b> Coming Soon\n\n"
        "This premium feature will allow you to:\n\n"
        "⚙️ <b>Setup Options:</b>\n"
        "• Custom keyword alerts\n"
        "• Hashtag monitoring\n"
        "• User mention tracking\n"
        "• Sentiment thresholds\n\n"
        "📊 <b>Alert Types:</b>\n"
        "• Instant notifications\n"
        "• Daily summaries\n"
        "• Weekly reports\n\n"
        "💡 <b>Currently Available:</b>\n"
        "Use the other X features to monitor TON discussions manually!",
        reply_markup=get_back_button(),
        parse_mode="HTML"
    )

async def back_to_X_menu(callback: CallbackQuery):
    """Return to main X menu"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐦 Influencer Posts", callback_data="X_influencer")],
        [InlineKeyboardButton(text="📈 TON Sentiment", callback_data="X_sentiment")],
        [InlineKeyboardButton(text="📊 X Stats", callback_data="X_stats")],
        [InlineKeyboardButton(text="⚡ Recent Alerts", callback_data="X_alerts")],
        [InlineKeyboardButton(text="🔍 Monitor Keywords", callback_data="X_monitor")]
    ])
    
    await callback.message.edit_text(
        "🐦 <b>X Monitor Dashboard</b>\n\n"
        "Track TON mentions, analyze influencer posts, and monitor market sentiment from X.\n\n"
        "Choose an option below:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

# Utility functions
def get_sentiment_emoji(sentiment: str) -> str:
    """Get emoji for sentiment"""
    return {
        'bullish': '📈',
        'bearish': '📉',
        'neutral': '➡️'
    }.get(sentiment.lower(), '➡️')

def get_back_button() -> InlineKeyboardMarkup:
    """Get back to menu button"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="back_to_X_menu")]
    ])

def register_X_handlers(dp):
    """Register X handlers with the dispatcher"""
    dp.include_router(router)
    logger.info("✅ X handlers registered")