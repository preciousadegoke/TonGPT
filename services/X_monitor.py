import asyncio
import logging
import tweepy
import sqlite3
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
import os
import time
import json

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class XMonitor:
    def __init__(self):
        # X API credentials
        self.api_key = os.getenv('X_API_KEY')
        self.api_secret = os.getenv('X_API_SECRET')
        self.access_token = os.getenv('X_ACCESS_TOKEN')
        self.access_token_secret = os.getenv('X_ACCESS_TOKEN_SECRET')
        self.bearer_token = os.getenv('X_BEARER_TOKEN')
        
        # Initialize X API client
        self.client = tweepy.Client(
            bearer_token=self.bearer_token,
            consumer_key=self.api_key,
            consumer_secret=self.api_secret,
            access_token=self.access_token,
            access_token_secret=self.access_token_secret,
            wait_on_rate_limit=True
        )
        
        # Initialize database
        self.init_database()
        
        # Rate limiting
        self.last_api_call = 0
        self.min_call_interval = 2.0  # 2 seconds between calls
        
        # TON-specific KOLs and official accounts
        self.ton_influencers = {
            # Official TON accounts
            'ton_blockchain': {'type': 'official', 'priority': 'critical'},
            'durov': {'type': 'founder', 'priority': 'critical'},
            'tonkeeper': {'type': 'official_wallet', 'priority': 'high'},
            'ton_foundation': {'type': 'official', 'priority': 'high'},
            'toncoin_org': {'type': 'official', 'priority': 'high'},
            
            # TON ecosystem KOLs
            'tonwhales': {'type': 'ecosystem', 'priority': 'high'},
            'getgems_io': {'type': 'nft_platform', 'priority': 'medium'},
            'dedust_io': {'type': 'defi', 'priority': 'medium'},
            'tonrocketbot': {'type': 'trading_bot', 'priority': 'medium'},
            'ston_fi': {'type': 'defi', 'priority': 'medium'},
            'tegro_money': {'type': 'defi', 'priority': 'medium'},
            
            # Community TON KOLs and Active Contributors
            'TemiJat': {'type': 'community_kol', 'priority': 'high'},
            's0meone_u_know': {'type': 'community_kol', 'priority': 'high'},
            'sazkvton': {'type': 'community_kol', 'priority': 'medium'},
            'bazzabrit': {'type': 'community_kol', 'priority': 'medium'},
            'GodsthroneTON': {'type': 'community_kol', 'priority': 'medium'},
            'PlushUtyaCTO': {'type': 'community_kol', 'priority': 'medium'},
            'Alhaxaie': {'type': 'community_kol', 'priority': 'medium'},
            'Bennie_krypt': {'type': 'community_kol', 'priority': 'medium'},
            'Active_Ustazz': {'type': 'community_kol', 'priority': 'medium'},
            'JERRY101x': {'type': 'community_kol', 'priority': 'medium'},
            '0xapaton': {'type': 'community_kol', 'priority': 'medium'},
            'satoshiequeen': {'type': 'community_kol', 'priority': 'medium'},
            'rogozov': {'type': 'community_kol', 'priority': 'medium'},
            'Andii__krypt': {'type': 'community_kol', 'priority': 'low'},
            'crypto_fox71906': {'type': 'community_kol', 'priority': 'low'},
            'Bartberry7': {'type': 'community_kol', 'priority': 'low'},
            'LizArtNFT_': {'type': 'community_kol', 'priority': 'low'},
            'chainspect_app': {'type': 'ecosystem', 'priority': 'medium'},
            'toncommunityhq': {'type': 'community', 'priority': 'medium'},
            'XMaximist': {'type': 'community_kol', 'priority': 'low'},
            'PAmbassadorHQ': {'type': 'community', 'priority': 'medium'},
            'AchukaGracious': {'type': 'community_kol', 'priority': 'low'},
            '0xc06': {'type': 'community_kol', 'priority': 'low'},
            'AltCryptoGems': {'type': 'community_kol', 'priority': 'medium'},
            'blockchain': {'type': 'general_crypto', 'priority': 'low'},
            'TmonkMonk': {'type': 'community_kol', 'priority': 'low'},
            'Boilyke2j': {'type': 'community_kol', 'priority': 'low'},
            'HAMIDixx': {'type': 'community_kol', 'priority': 'low'},
            'alaminbanshara': {'type': 'community_kol', 'priority': 'low'},
            'jakariyax2': {'type': 'community_kol', 'priority': 'low'},
            'TasteLabsAI': {'type': 'ecosystem', 'priority': 'low'},
            'Ibkhalieel': {'type': 'community_kol', 'priority': 'low'},
            'xiaojianjian567': {'type': 'community_kol', 'priority': 'low'},
            '0xleeBTC': {'type': 'community_kol', 'priority': 'low'},
            'AllofGreg': {'type': 'community_kol', 'priority': 'low'},
            'Enyioma_Ifeanyi': {'type': 'community_kol', 'priority': 'low'},
            'sammy_vou': {'type': 'community_kol', 'priority': 'low'},
            'TheOtherCryptoG': {'type': 'community_kol', 'priority': 'low'},
            'Mhasaan49': {'type': 'community_kol', 'priority': 'low'},
            'MaziMarKov': {'type': 'community_kol', 'priority': 'low'},
            'CodaxOG': {'type': 'community_kol', 'priority': 'low'},
            'cyberwarriorleo': {'type': 'community_kol', 'priority': 'low'},
            'Olanihundc': {'type': 'community_kol', 'priority': 'low'},
            'lofitheyeti': {'type': 'community_kol', 'priority': 'low'},
            'DefiwithSH': {'type': 'community_kol', 'priority': 'low'},
            '_aremu_001': {'type': 'community_kol', 'priority': 'low'},
            'Dot_kenet1': {'type': 'community_kol', 'priority': 'low'},
            'ade_alayo69': {'type': 'community_kol', 'priority': 'low'},
            'Riil_ETHbz0x': {'type': 'community_kol', 'priority': 'low'},
            'Legionweb3': {'type': 'community_kol', 'priority': 'low'},
            'JimmyOgb12': {'type': 'community_kol', 'priority': 'low'},
            'MzteVal': {'type': 'community_kol', 'priority': 'low'},
            'BZakar_': {'type': 'community_kol', 'priority': 'low'},
            '0x_micro': {'type': 'community_kol', 'priority': 'low'},
            'tonmyanmar': {'type': 'community', 'priority': 'low'},
            'bits71280300': {'type': 'community_kol', 'priority': 'low'},
            'Vindicatedchidi': {'type': 'community_kol', 'priority': 'low'},
            'cryptosymbiiote': {'type': 'community_kol', 'priority': 'low'},
            'Joeconceptss': {'type': 'community_kol', 'priority': 'low'},
            'ahboyash': {'type': 'community_kol', 'priority': 'low'},
            'niccary': {'type': 'community_kol', 'priority': 'low'},
            'Mamanaesha': {'type': 'community_kol', 'priority': 'low'},
            'ImCryptOpus': {'type': 'community_kol', 'priority': 'low'},
            'ChristiaanDefi': {'type': 'community_kol', 'priority': 'low'},
            'Crypto_vibes__': {'type': 'community_kol', 'priority': 'low'},
            '0xCryptoBeat': {'type': 'community_kol', 'priority': 'low'},
            'toygersofficial': {'type': 'ecosystem', 'priority': 'low'},
            'oraclewilliams': {'type': 'community_kol', 'priority': 'low'},
            'JanaCryptoQueen': {'type': 'community_kol', 'priority': 'low'},
            'ShedrackH87620': {'type': 'community_kol', 'priority': 'low'},
            'gabrelyanov': {'type': 'community_kol', 'priority': 'low'},
            'smooth_org': {'type': 'ecosystem', 'priority': 'low'},
            'marablossom': {'type': 'community_kol', 'priority': 'low'},
            'FB3_DeFi': {'type': 'community_kol', 'priority': 'low'},
            'MoonKing___': {'type': 'community_kol', 'priority': 'low'},
            'AleaResearch': {'type': 'research', 'priority': 'medium'},
            'm0nsh1n31': {'type': 'community_kol', 'priority': 'low'},
            'Sirhassan21': {'type': 'community_kol', 'priority': 'low'},
            'JBoyce40367': {'type': 'community_kol', 'priority': 'low'},
            'moo9000': {'type': 'community_kol', 'priority': 'low'},
            'KhanShar86614': {'type': 'community_kol', 'priority': 'low'},
            'tonstationgames': {'type': 'ecosystem', 'priority': 'medium'},
            'Altverse001': {'type': 'community_kol', 'priority': 'low'},
            'genwealth_eth': {'type': 'community_kol', 'priority': 'low'},
            'samuelfrid77312': {'type': 'community_kol', 'priority': 'low'},
            'Resolutehive': {'type': 'community_kol', 'priority': 'low'},
            
            # General crypto influencers who might mention TON
            'elonmusk': {'type': 'crypto_influencer', 'priority': 'high'},
            'VitalikButerin': {'type': 'crypto_influencer', 'priority': 'medium'},
            'CZ_Binance': {'type': 'crypto_influencer', 'priority': 'medium'},
            'justinsuntron': {'type': 'crypto_influencer', 'priority': 'low'},
        }
        
        # TON memecoin patterns and indicators
        self.memecoin_indicators = [
            # Common memecoin phrases
            r'new\s+token\s+on\s+ton', r'ton\s+memecoin', r'ton\s+gem',
            r'launching\s+on\s+ton', r'ton\s+network.*token',
            r'dedust.*new', r'ston\.fi.*new', r'ton\s+rocket.*new',
            
            # Contract address patterns for TON
            r'EQ[A-Za-z0-9_-]{46}',  # TON address format
            r'UQ[A-Za-z0-9_-]{46}',  # TON address format
            
            # Memecoin launch indicators
            r'just\s+launched.*ton', r'new\s+on\s+ton', r'ton.*100x',
            r'ton.*moonshot', r'ton.*early', r'first.*ton.*meme'
        ]
        
        # Comprehensive TON ecosystem keywords
        self.ton_keywords = {
            'core': [
                'TON blockchain', 'Toncoin', 'The Open Network', '$TON',
                'ton.org', 'TON Foundation', 'Telegram Open Network'
            ],
            'infrastructure': [
                'TON DNS', 'TON Storage', 'TON Proxy', 'TON validators',
                'TON Core', 'TON Smart Contracts', 'TON API'
            ],
            'defi': [
                'DeDust', 'STON.fi', 'Tegro', 'TON DEX', 'TON DeFi',
                'TON liquidity', 'TON farming', 'TON staking'
            ],
            'tools': [
                'Tonkeeper', 'TON Wallet', 'TonScan', 'TON Explorer',
                'TON Rocket', 'TON Whales', 'TON Stats'
            ],
            'nft': [
                'GetGems', 'TON NFT', 'TON Diamonds', 'Fragment.com',
                'TON collectibles'
            ],
            'memecoins': [
                'TON memecoin', 'TON gem', 'TON token', 'new on TON',
                'TON launch', 'TON moonshot'
            ]
        }
    
    def init_database(self):
        """Initialize enhanced database schema"""
        conn = sqlite3.connect('ton_ecosystem.db')
        cursor = conn.cursor()
        
        # Enhanced tweets table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tweets (
                id TEXT PRIMARY KEY,
                username TEXT,
                content TEXT,
                created_at TIMESTAMP,
                retweet_count INTEGER,
                like_count INTEGER,
                reply_count INTEGER,
                is_ton_related BOOLEAN,
                is_influencer BOOLEAN,
                influencer_type TEXT,
                priority TEXT,
                sentiment_score REAL,
                category TEXT,
                contains_contract_address BOOLEAN,
                contract_addresses TEXT,
                memecoin_score REAL,
                analyzed_at TIMESTAMP,
                alert_sent BOOLEAN DEFAULT FALSE
            )
        ''')
        
        # Following tracking table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS influencer_following (
                influencer_username TEXT,
                following_username TEXT,
                following_user_id TEXT,
                followed_at TIMESTAMP,
                is_new_follow BOOLEAN,
                follower_count INTEGER,
                account_created_at TIMESTAMP,
                bio TEXT,
                verified BOOLEAN,
                PRIMARY KEY (influencer_username, following_username)
            )
        ''')
        
        # Memecoin tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ton_memecoins (
                contract_address TEXT PRIMARY KEY,
                token_name TEXT,
                token_symbol TEXT,
                discovered_at TIMESTAMP,
                first_tweet_id TEXT,
                discoverer_username TEXT,
                initial_followers INTEGER,
                current_status TEXT,
                platform TEXT
            )
        ''')
        
        # KOL alpha signals
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alpha_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_type TEXT,
                source_username TEXT,
                target_username TEXT,
                action TEXT,
                confidence_score REAL,
                detected_at TIMESTAMP,
                content TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS monitoring_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    async def rate_limit_delay(self):
        """Enhanced rate limiting"""
        current_time = time.time()
        time_since_last_call = current_time - self.last_api_call
        
        if time_since_last_call < self.min_call_interval:
            wait_time = self.min_call_interval - time_since_last_call
            await asyncio.sleep(wait_time)
        
        self.last_api_call = time.time()
    
    def build_comprehensive_ton_query(self) -> str:
        """Build optimized query for all TON ecosystem content"""
        # Core TON terms that are specific enough
        core_terms = [
            '"TON blockchain"', '"Toncoin"', '"The Open Network"',
            '$TON', 'ton.org', '"TON Foundation"'
        ]
        
        # DeFi and ecosystem terms
        ecosystem_terms = [
            'DeDust', 'STON.fi', 'Tegro', 'Tonkeeper', 'GetGems',
            '"TON DEX"', '"TON DeFi"', '"TON NFT"'
        ]
        
        # Memecoin discovery terms
        memecoin_terms = [
            '"new token on TON"', '"TON memecoin"', '"launching on TON"',
            '"TON gem"', '"new on TON"'
        ]
        
        all_terms = core_terms + ecosystem_terms + memecoin_terms
        query = f"({' OR '.join(all_terms)}) -is:retweet lang:en"
        
        return query
    
    def extract_ton_contract_addresses(self, text: str) -> List[str]:
        """Extract TON contract addresses from tweet text"""
        # TON address patterns
        ton_patterns = [
            r'EQ[A-Za-z0-9_-]{46}',  # Standard TON address
            r'UQ[A-Za-z0-9_-]{46}',  # Another TON format
        ]
        
        addresses = []
        for pattern in ton_patterns:
            matches = re.findall(pattern, text)
            addresses.extend(matches)
        
        return list(set(addresses))  # Remove duplicates
    
    def calculate_memecoin_score(self, tweet: Dict) -> float:
        """Calculate likelihood that this is a TON memecoin announcement"""
        text = tweet.get('text', '').lower()
        score = 0.0
        
        # Check for memecoin indicators
        for pattern in self.memecoin_indicators:
            if re.search(pattern, text, re.IGNORECASE):
                score += 0.2
        
        # Contract address presence
        if self.extract_ton_contract_addresses(text):
            score += 0.3
        
        # Launch/new token keywords
        launch_words = ['launch', 'new token', 'just dropped', 'introducing', 'live now']
        for word in launch_words:
            if word in text:
                score += 0.1
        
        # TON-specific platforms mentioned
        ton_platforms = ['dedust', 'ston.fi', 'ton rocket', 'getgems']
        for platform in ton_platforms:
            if platform in text:
                score += 0.15
        
        # Memecoin hype words
        hype_words = ['moon', 'gem', '100x', 'early', 'alpha', 'ape']
        hype_count = sum(1 for word in hype_words if word in text)
        score += min(hype_count * 0.1, 0.3)  # Cap at 0.3
        
        return min(score, 1.0)  # Cap at 1.0
    
    def categorize_ton_content(self, tweet: Dict) -> str:
        """Categorize TON-related content"""
        text = tweet.get('text', '').lower()
        
        # Check categories in order of specificity
        if any(indicator in text for indicator in ['memecoin', 'new token', 'launch', 'gem']):
            return 'memecoin'
        elif any(defi in text for defi in ['dedust', 'ston.fi', 'tegro', 'dex', 'swap']):
            return 'defi'
        elif any(nft in text for nft in ['getgems', 'nft', 'collectible']):
            return 'nft'
        elif any(infra in text for infra in ['validator', 'staking', 'mining']):
            return 'infrastructure'
        elif any(dev in text for dev in ['smart contract', 'dapp', 'development']):
            return 'development'
        else:
            return 'general'
    
    def is_ton_specific(self, tweet: Dict) -> bool:
        """Enhanced TON detection that avoids other blockchain confusion"""
        text = tweet.get('text', '').lower()
        
        # Explicit TON blockchain indicators
        ton_explicit = [
            'ton blockchain', 'toncoin', 'the open network',
            '$ton', 'ton.org', 'ton foundation', 'telegram open network'
        ]
        
        for indicator in ton_explicit:
            if indicator in text:
                return True
        
        # TON ecosystem specific terms
        ton_ecosystem = [
            'dedust', 'ston.fi', 'tegro', 'tonkeeper', 'getgems',
            'ton rocket', 'ton whales', 'fragment.com'
        ]
        
        for term in ton_ecosystem:
            if term in text:
                return True
        
        # If just "TON" mentioned, check it's not other blockchains
        if re.search(r'\bton\b', text, re.IGNORECASE):
            # Exclude if other blockchains mentioned
            other_chains = ['ethereum', 'bitcoin', 'solana', 'polygon', 'bsc', 'avalanche']
            if any(chain in text for chain in other_chains):
                return False
            
            # Include if crypto context present
            crypto_context = [
                'blockchain', 'crypto', 'defi', 'token', 'coin', 'wallet',
                'mining', 'staking', 'dapp', 'smart contract'
            ]
            return any(context in text for context in crypto_context)
        
        return False
    
    async def monitor_kol_following(self, username: str):
        """Monitor who a KOL is following for alpha signals"""
        try:
            await self.rate_limit_delay()
            
            # Get user info
            user = self.client.get_user(username=username)
            if not user.data:
                return
            
            user_id = user.data.id
            
            # Get their following list (limited by API)
            following = self.client.get_users_following(
                id=user_id,
                max_results=100,  # API limit
                user_fields=['created_at', 'public_metrics', 'description', 'verified']
            )
            
            if following.data:
                conn = sqlite3.connect('ton_ecosystem.db')
                cursor = conn.cursor()
                
                for followed_user in following.data:
                    # Check if this is a new follow
                    cursor.execute(
                        "SELECT * FROM influencer_following WHERE influencer_username = ? AND following_username = ?",
                        (username, followed_user.username)
                    )
                    
                    is_new = cursor.fetchone() is None
                    
                    # Store following relationship
                    cursor.execute('''
                        INSERT OR REPLACE INTO influencer_following 
                        (influencer_username, following_username, following_user_id, followed_at,
                         is_new_follow, follower_count, account_created_at, bio, verified)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        username, followed_user.username, followed_user.id,
                        datetime.utcnow(), is_new,
                        followed_user.public_metrics.get('followers_count', 0),
                        followed_user.created_at, followed_user.description or '',
                        followed_user.verified or False
                    ))
                    
                    # Create alpha signal for new follows of small accounts
                    if is_new and followed_user.public_metrics.get('followers_count', 0) < 10000:
                        self.create_alpha_signal(
                            'new_follow', username, followed_user.username,
                            f"KOL {username} followed small account {followed_user.username}",
                            0.7
                        )
                
                conn.commit()
                conn.close()
                
        except Exception as e:
            logger.error(f"Error monitoring {username} following: {e}")
    
    def create_alpha_signal(self, signal_type: str, source: str, target: str, content: str, confidence: float):
        """Create an alpha signal entry"""
        conn = sqlite3.connect('ton_ecosystem.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO alpha_signals 
            (signal_type, source_username, target_username, action, confidence_score, detected_at, content)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (signal_type, source, target, 'follow', confidence, datetime.utcnow(), content))
        
        conn.commit()
        conn.close()
    
    async def discover_new_ton_accounts(self):
        """Discover new TON-related accounts through various signals"""
        # Search for very recent TON mentions from small accounts
        query = '("new on TON" OR "TON launch" OR "TON token") min_faves:0'
        
        try:
            await self.rate_limit_delay()
            
            tweets_response = self.client.search_recent_tweets(
                query=query,
                max_results=100,
                tweet_fields=['created_at', 'author_id', 'public_metrics'],
                user_fields=['username', 'public_metrics', 'created_at'],
                expansions=['author_id']
            )
            
            if tweets_response.data and tweets_response.includes:
                users = {user.id: user for user in tweets_response.includes.get('users', [])}
                
                for tweet in tweets_response.data:
                    user = users.get(tweet.author_id)
                    if user and user.public_metrics['followers_count'] < 1000:  # Small accounts
                        # This could be an early alpha account
                        logger.info(f"Discovered potential alpha account: @{user.username} ({user.public_metrics['followers_count']} followers)")
                        
        except Exception as e:
            logger.error(f"Error in account discovery: {e}")
    
    async def enhanced_monitoring_cycle(self):
        """Main monitoring loop with all features"""
        logger.info("Starting enhanced TON ecosystem monitoring...")
        cycle_count = 0
        
        while True:
            try:
                cycle_count += 1
                logger.info(f"Starting monitoring cycle #{cycle_count}")
                
                # 1. Search for TON content
                await self.rate_limit_delay()
                query = self.build_comprehensive_ton_query()
                tweets_response = self.client.search_recent_tweets(
                    query=query,
                    max_results=100,
                    tweet_fields=['created_at', 'author_id', 'public_metrics', 'text'],
                    user_fields=['username', 'verified', 'public_metrics'],
                    expansions=['author_id']
                )
                
                processed = 0
                memecoin_alerts = 0
                
                if tweets_response.data:
                    users = {user.id: user for user in tweets_response.includes.get('users', [])}
                    
                    for tweet in tweets_response.data:
                        user = users.get(tweet.author_id)
                        if user and self.is_ton_specific(tweet):
                            # Enhanced analysis
                            category = self.categorize_ton_content(tweet)
                            memecoin_score = self.calculate_memecoin_score(tweet)
                            contract_addresses = self.extract_ton_contract_addresses(tweet['text'])
                            
                            # Store with enhanced data
                            self.store_enhanced_tweet(tweet, user, category, memecoin_score, contract_addresses)
                            processed += 1
                            
                            # High-value alerts
                            if (memecoin_score > 0.6 or 
                                user.username.lower() in [u.lower() for u in self.ton_influencers] or
                                contract_addresses):
                                await self.send_enhanced_alert(tweet, user, category, memecoin_score, contract_addresses)
                                memecoin_alerts += 1
                
                # 2. Monitor KOL following (every 3rd cycle to avoid rate limits)
                if cycle_count % 3 == 0:
                    priority_kols = [k for k, v in self.ton_influencers.items() if v['priority'] in ['critical', 'high']]
                    for kol in priority_kols[:2]:  # Monitor 2 KOLs per cycle
                        await self.monitor_kol_following(kol)
                        await asyncio.sleep(5)  # Extra delay between KOL monitoring
                
                # 3. Discover new accounts (every 5th cycle)
                if cycle_count % 5 == 0:
                    await self.discover_new_ton_accounts()
                
                logger.info(f"Cycle #{cycle_count} complete: {processed} TON tweets processed, {memecoin_alerts} alerts sent")
                
                # Wait 8 minutes between cycles (more conservative)
                await asyncio.sleep(480)
                
            except tweepy.TooManyRequests:
                logger.warning("Rate limit hit. Sleeping 20 minutes...")
                await asyncio.sleep(1200)
            except Exception as e:
                logger.error(f"Error in monitoring cycle: {e}")
                await asyncio.sleep(300)  # 5 minute recovery
    
    def store_enhanced_tweet(self, tweet: Dict, user, category: str, memecoin_score: float, addresses: List[str]):
        """Store tweet with enhanced analysis data"""
        conn = sqlite3.connect('ton_ecosystem.db')
        cursor = conn.cursor()
        
        is_influencer = user.username.lower() in [u.lower() for u in self.ton_influencers]
        influencer_data = self.ton_influencers.get(user.username.lower(), {})
        
        cursor.execute('''
            INSERT OR REPLACE INTO tweets 
            (id, username, content, created_at, retweet_count, like_count, reply_count,
             is_ton_related, is_influencer, influencer_type, priority, sentiment_score,
             category, contains_contract_address, contract_addresses, memecoin_score, analyzed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            tweet['id'], user.username, tweet['text'], tweet['created_at'],
            tweet['public_metrics']['retweet_count'], tweet['public_metrics']['like_count'],
            tweet['public_metrics']['reply_count'], True, is_influencer,
            influencer_data.get('type'), influencer_data.get('priority'),
            self.calculate_sentiment(tweet['text']), category,
            bool(addresses), json.dumps(addresses), memecoin_score, datetime.utcnow()
        ))
        
        # Store memecoin info if detected
        if memecoin_score > 0.5 and addresses:
            for address in addresses:
                cursor.execute('''
                    INSERT OR IGNORE INTO ton_memecoins
                    (contract_address, discovered_at, first_tweet_id, discoverer_username, initial_followers)
                    VALUES (?, ?, ?, ?, ?)
                ''', (address, datetime.utcnow(), tweet['id'], user.username, user.public_metrics['followers_count']))
        
        conn.commit()
        conn.close()
    
    def calculate_sentiment(self, text: str) -> float:
        """Enhanced sentiment analysis"""
        positive_words = ['good', 'great', 'excellent', 'amazing', 'bullish', 'moon', 'up', 'rise', 'pump', 'gem', 'alpha']
        negative_words = ['bad', 'terrible', 'awful', 'bearish', 'down', 'fall', 'dump', 'crash', 'scam', 'rug']
        
        text_lower = text.lower()
        positive_count = sum(1 for word in positive_words if word in text_lower)
        negative_count = sum(1 for word in negative_words if word in text_lower)
        
        total_words = len(text.split())
        if total_words == 0:
            return 0.0
        
        sentiment = (positive_count - negative_count) / total_words
        return max(-1.0, min(1.0, sentiment))
    
    async def send_enhanced_alert(self, tweet: Dict, user, category: str, memecoin_score: float, addresses: List[str]):
        """Send enhanced alerts with more context"""
        alert_parts = []
        
        # Priority level
        if user.username.lower() in self.ton_influencers:
            priority = self.ton_influencers[user.username.lower()]['priority']
            alert_parts.append(f"🚨 {priority.upper()} PRIORITY")
        
        # Category
        alert_parts.append(f"📂 {category.upper()}")
        
        # User info
        alert_parts.append(f"👤 @{user.username} ({user.public_metrics['followers_count']} followers)")
        
        # Memecoin score
        if memecoin_score > 0.6:
            alert_parts.append(f"🪙 Memecoin Score: {memecoin_score:.2f}")
        
        # Contract addresses
        if addresses:
            alert_parts.append(f"📝 Contracts: {', '.join(addresses[:2])}")
        
        # Tweet content
        alert_parts.append(f"💬 \"{tweet['text'][:150]}{'...' if len(tweet['text']) > 150 else ''}\"")
        
        alert_message = "\n".join(alert_parts)
        logger.warning(f"ENHANCED ALERT:\n{alert_message}")
        
        # Here you would send to your preferred notification system
        # (Discord, Telegram, Slack, etc.)

# Usage
async def main():
    monitor = XMonitor()
    await monitor.enhanced_monitoring_cycle()

if __name__ == "__main__":
    asyncio.run(main())