import tweepy
from textblob import TextBlob
import json
import os
from dotenv import load_dotenv
from utils.redis_conn import redis_client

load_dotenv()
X_API_KEY = os.getenv("X_API_KEY")
X_API_SECRET = os.getenv("X_API_SECRET")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET")

def analyze_tweets():
    cache_key = "influencer_posts"
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    auth = tweepy.OAuthHandler(X_API_KEY, X_API_SECRET)
    auth.set_access_token(X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET)
    x_api = tweepy.API(auth, wait_on_rate_limit=True)
    
    query = "from:verified TON OR Toncoin OR The Open Network -filter:retweets"
    tweets = x_api.search_tweets(q=query, lang="en", result_type="recent", count=10)
    results = []
    for tweet in tweets:
        if tweet.user.followers_count > 10000:  # Influencer threshold
            sentiment = TextBlob(tweet.text).sentiment.polarity
            results.append({
                "user": tweet.user.screen_name,
                "text": tweet.text,
                "sentiment": "bullish" if sentiment > 0 else "bearish" if sentiment < 0 else "neutral",
                "followers": tweet.user.followers_count
            })
    redis_client.setex(cache_key, 3600, json.dumps(results))  # Cache for 1 hour
    return results