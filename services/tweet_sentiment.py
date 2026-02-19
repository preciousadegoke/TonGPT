import tweepy
from textblob import TextBlob
import json
import os
import logging
from dotenv import load_dotenv
from utils.redis_conn import redis_client

logger = logging.getLogger(__name__)
load_dotenv()

def analyze_tweets():
    """Analyze TON-related tweets with X API v2"""
    cache_key = "influencer_posts"
    
    # Check cache first
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    try:
        # X API v2 authentication
        client = tweepy.Client(
            bearer_token=os.getenv("X_BEARER_TOKEN"),  # Add this to your .env
            consumer_key=os.getenv("X_API_KEY"),
            consumer_secret=os.getenv("X_API_SECRET"),
            access_token=os.getenv("X_ACCESS_TOKEN"),
            access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET")
        )
        
        # Search for TON-related tweets from verified accounts
        query = "(TON OR Toncoin OR \"The Open Network\") -is:retweet -is:reply has:links lang:en"
        response = client.search_recent_tweets(
            query=query,
            max_results=15,
            tweet_fields=["author_id", "created_at", "public_metrics"],
            expansions=["author_id"],
            user_fields=["username", "name", "verified", "public_metrics"]
        )
        
        if not response.data:
            return []
        
        # Get user information
        users = {user.id: user for user in response.includes['users']}
        results = []
        
        for tweet in response.data:
            user = users.get(tweet.author_id)
            if user and user.public_metrics['followers_count'] > 10000:
                sentiment = TextBlob(tweet.text).sentiment.polarity
                results.append({
                    "user": user.username,
                    "name": user.name,
                    "text": tweet.text[:200] + "..." if len(tweet.text) > 200 else tweet.text,
                    "sentiment": "bullish" if sentiment > 0.1 else "bearish" if sentiment < -0.1 else "neutral",
                    "followers": user.public_metrics['followers_count'],
                    "verified": user.verified,
                    "likes": tweet.public_metrics['like_count'],
                    "retweets": tweet.public_metrics['retweet_count']
                })
        
        # Cache results
        redis_client.setex(cache_key, 1800, json.dumps(results))  # 30 minutes
        return results
        
    except Exception as e:
        logger.error(f"X API error: {e}")
        return []     