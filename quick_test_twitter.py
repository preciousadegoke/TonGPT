# quick_test_X.py
import os
import tweepy
from dotenv import load_dotenv

load_dotenv()

auth = tweepy.OAuth1UserHandler(
    os.getenv("X_API_KEY"),
    os.getenv("X_API_SECRET"), 
    os.getenv("X_ACCESS_TOKEN"),
    os.getenv("X_ACCESS_TOKEN_SECRET")
)

api = tweepy.API(auth)
try:
    user = api.verify_credentials()
    print(f"✅ X API connected: @{user.screen_name}")
except Exception as e:
    print(f"❌ X API failed: {e}")