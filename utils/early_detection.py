import asyncio
import aiohttp
import sqlite3
import time
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
import json
import threading
from contextlib import asynccontextmanager

 
try:
    import spacy
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False
    print("Warning: spaCy not installed. Text analysis features will be limited.")
    print("Install with: pip install spacy && python -m spacy download en_core_web_sm")

logger = logging.getLogger(__name__)

@dataclass
class EarlyMemecoin:
    """Data structure for early detected memecoins"""
    address: str
    symbol: str
    name: str
    pair_address: str = ""
    dex: str = ""
    initial_liquidity: float = 0.0
    first_detected: datetime = field(default_factory=datetime.now)
    detection_method: str = "api_scan"
    confidence_score: float = 0.0
    
    # Analysis results
    is_memecoin: bool = False
    has_social_signals: bool = False
    risk_level: str = "unknown"  # low, medium, high, critical
    
    # Market data
    price: float = 0.0
    volume_24h: float = 0.0
    holder_count: int = 0
    
    def to_dict(self) -> Dict:
        return {
            'address': self.address,
            'symbol': self.symbol,
            'name': self.name,
            'pair_address': self.pair_address,
            'dex': self.dex,
            'initial_liquidity': self.initial_liquidity,
            'first_detected': self.first_detected.isoformat(),
            'detection_method': self.detection_method,
            'confidence_score': self.confidence_score,
            'is_memecoin': self.is_memecoin,
            'has_social_signals': self.has_social_signals,
            'risk_level': self.risk_level,
            'price': self.price,
            'volume_24h': self.volume_24h,
            'holder_count': self.holder_count
        }

class TokenAnalyzer:
    """Advanced token analysis using spaCy and pattern matching"""
    
    def __init__(self):
        self.nlp = None
        if SPACY_AVAILABLE:
            try:
                self.nlp = spacy.load("en_core_web_sm")
            except OSError:
                logger.warning("spaCy English model not found. Text analysis will be basic.")
        
        # Memecoin indicators
        self.animal_keywords = {
            'dog', 'cat', 'frog', 'ape', 'monkey', 'fish', 'bird', 'lion', 'tiger',
            'elephant', 'whale', 'dolphin', 'shark', 'bear', 'bull', 'pig', 'cow'
        }
        
        self.meme_keywords = {
            'pepe', 'wojak', 'chad', 'based', 'cringe', 'sigma', 'alpha', 'beta',
            'gigachad', 'doomer', 'boomer', 'zoomer', 'coomer', 'soyjak'
        }
        
        self.crypto_slang = {
            'moon', 'lambo', 'diamond', 'hands', 'hodl', 'fud', 'fomo', 'ape',
            'degen', 'wagmi', 'ngmi', 'gm', 'ser', 'anon', 'chad', 'pump', 'dump'
        }
        
        self.viral_indicators = {
            'viral', 'trending', 'community', 'meme', 'token', 'coin', 'gem',
            'moonshot', 'rocket', 'explosion', 'fire', 'hot', 'crazy', 'insane'
        }
    
    def analyze_token(self, name: str, symbol: str, description: str = "") -> Dict:
        """Comprehensive token analysis"""
        text_content = f"{name} {symbol} {description}".lower()
        
        analysis = {
            'memecoin_score': 0.0,
            'animal_reference': False,
            'meme_reference': False,
            'crypto_slang_usage': False,
            'viral_indicators': False,
            'sentiment': 'neutral',
            'risk_flags': []
        }
        
        # Basic keyword matching
        analysis['animal_reference'] = any(animal in text_content for animal in self.animal_keywords)
        analysis['meme_reference'] = any(meme in text_content for meme in self.meme_keywords)
        analysis['crypto_slang_usage'] = any(slang in text_content for slang in self.crypto_slang)
        analysis['viral_indicators'] = any(viral in text_content for viral in self.viral_indicators)
        
        # Calculate memecoin score
        score = 0.0
        if analysis['animal_reference']:
            score += 0.3
        if analysis['meme_reference']:
            score += 0.4
        if analysis['crypto_slang_usage']:
            score += 0.2
        if analysis['viral_indicators']:
            score += 0.1
        
        # spaCy analysis if available
        if self.nlp and text_content:
            try:
                doc = self.nlp(text_content)
                
                # Sentiment analysis (basic)
                positive_words = sum(1 for token in doc if token.sentiment > 0)
                negative_words = sum(1 for token in doc if token.sentiment < 0)
                
                if positive_words > negative_words:
                    analysis['sentiment'] = 'positive'
                elif negative_words > positive_words:
                    analysis['sentiment'] = 'negative'
                
                # Named entity recognition for additional context
                entities = [ent.text.lower() for ent in doc.ents]
                if any(ent in self.animal_keywords for ent in entities):
                    score += 0.1
                    
            except Exception as e:
                logger.debug(f"spaCy analysis failed: {e}")
        
        # Risk flag detection
        risk_patterns = [
            r'100x|1000x',  # Unrealistic promises
            r'safe|safu',   # Common scam words
            r'rug.*pull',   # Rug pull references
            r'moon.*guaranteed',  # Guaranteed moon
        ]
        
        for pattern in risk_patterns:
            if re.search(pattern, text_content, re.IGNORECASE):
                analysis['risk_flags'].append(f"Suspicious pattern: {pattern}")
        
        analysis['memecoin_score'] = min(score, 1.0)
        return analysis

class DEXMonitor:
    """Monitor DEX APIs for new token pairs"""
    
    def __init__(self):
        self.session = None
        self.last_check = {}
        self.known_pairs = set()
        
        # DEX API endpoints
        self.dex_apis = {
            'stonfi': {
                'url': 'https://api.ston.fi/v1/markets',
                'pairs_key': 'asset_list',
                'update_interval': 30
            },
            'dedust': {
                'url': 'https://api.dedust.io/v2/pools',
                'pairs_key': 'pools',
                'update_interval': 45
            }
        }
    
    async def scan_new_pairs(self) -> List[EarlyMemecoin]:
        """Scan DEX APIs for new trading pairs"""
        new_tokens = []
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            for dex_name, config in self.dex_apis.items():
                task = self._scan_dex(session, dex_name, config)
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, list):
                    new_tokens.extend(result)
                elif isinstance(result, Exception):
                    logger.error(f"DEX scan error: {result}")
        
        return new_tokens
    
    async def _scan_dex(self, session: aiohttp.ClientSession, dex_name: str, config: Dict) -> List[EarlyMemecoin]:
        """Scan specific DEX for new pairs"""
        try:
            # Rate limiting
            last_check = self.last_check.get(dex_name, 0)
            if time.time() - last_check < config['update_interval']:
                return []
            
            async with session.get(config['url'], timeout=10) as response:
                if response.status != 200:
                    return []
                
                data = await response.json()
                pairs_data = data.get(config['pairs_key'], [])
                
                new_tokens = []
                for pair in pairs_data:
                    token = self._extract_token_from_pair(pair, dex_name)
                    if token and self._is_new_token(token):
                        new_tokens.append(token)
                
                self.last_check[dex_name] = time.time()
                return new_tokens
                
        except Exception as e:
            logger.error(f"Error scanning {dex_name}: {e}")
            return []
    
    def _extract_token_from_pair(self, pair_data: Dict, dex_name: str) -> Optional[EarlyMemecoin]:
        """Extract token information from pair data"""
        try:
            # This is simplified - actual implementation depends on API structure
            token_info = pair_data.get('token0', pair_data.get('base_token', {}))
            
            if not token_info:
                return None
            
            symbol = token_info.get('symbol', '').upper()
            name = token_info.get('name', '')
            address = token_info.get('address', '')
            
            if not all([symbol, name, address]):
                return None
            
            # Extract liquidity information
            liquidity = float(pair_data.get('liquidity_usd', 0))
            
            return EarlyMemecoin(
                address=address,
                symbol=symbol,
                name=name,
                pair_address=pair_data.get('address', ''),
                dex=dex_name,
                initial_liquidity=liquidity,
                detection_method='dex_scan'
            )
            
        except Exception as e:
            logger.debug(f"Error extracting token from pair: {e}")
            return None
    
    def _is_new_token(self, token: EarlyMemecoin) -> bool:
        """Check if token is new (not seen before)"""
        token_key = f"{token.address}_{token.dex}"
        
        if token_key in self.known_pairs:
            return False
        
        # Basic filters for potentially interesting tokens
        if token.initial_liquidity < 500:  # Less than $500 liquidity
            return False
        
        if len(token.symbol) > 10:  # Very long symbols are often scams
            return False
        
        self.known_pairs.add(token_key)
        return True

class EarlyDetectionDatabase:
    """Database for storing early detections"""
    
    def __init__(self, db_path: str = "early_detections.db"):
        self.db_path = db_path
        self.lock = threading.RLock()
        self._init_database()
    
    def _init_database(self):
        """Initialize detection database"""
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS early_detections (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        address TEXT UNIQUE,
                        symbol TEXT,
                        name TEXT,
                        pair_address TEXT,
                        dex TEXT,
                        initial_liquidity REAL,
                        first_detected DATETIME,
                        detection_method TEXT,
                        confidence_score REAL,
                        is_memecoin BOOLEAN,
                        has_social_signals BOOLEAN,
                        risk_level TEXT,
                        price REAL DEFAULT 0,
                        volume_24h REAL DEFAULT 0,
                        holder_count INTEGER DEFAULT 0,
                        status TEXT DEFAULT 'active'
                    )
                ''')
                
                # Analysis results table
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS token_analysis (
                        address TEXT PRIMARY KEY,
                        memecoin_score REAL,
                        animal_reference BOOLEAN,
                        meme_reference BOOLEAN,
                        crypto_slang_usage BOOLEAN,
                        viral_indicators BOOLEAN,
                        sentiment TEXT,
                        risk_flags TEXT,
                        analyzed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (address) REFERENCES early_detections (address)
                    )
                ''')
    
    def store_detection(self, token: EarlyMemecoin, analysis: Dict = None):
        """Store early detection in database"""
        with self.lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    # Store main detection
                    conn.execute('''
                        INSERT OR REPLACE INTO early_detections 
                        (address, symbol, name, pair_address, dex, initial_liquidity,
                         first_detected, detection_method, confidence_score, is_memecoin,
                         has_social_signals, risk_level, price, volume_24h, holder_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        token.address, token.symbol, token.name, token.pair_address,
                        token.dex, token.initial_liquidity, token.first_detected,
                        token.detection_method, token.confidence_score, token.is_memecoin,
                        token.has_social_signals, token.risk_level, token.price,
                        token.volume_24h, token.holder_count
                    ))
                    
                    # Store analysis if provided
                    if analysis:
                        conn.execute('''
                            INSERT OR REPLACE INTO token_analysis
                            (address, memecoin_score, animal_reference, meme_reference,
                             crypto_slang_usage, viral_indicators, sentiment, risk_flags)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            token.address, analysis.get('memecoin_score', 0),
                            analysis.get('animal_reference', False),
                            analysis.get('meme_reference', False),
                            analysis.get('crypto_slang_usage', False),
                            analysis.get('viral_indicators', False),
                            analysis.get('sentiment', 'neutral'),
                            json.dumps(analysis.get('risk_flags', []))
                        ))
                        
            except Exception as e:
                logger.error(f"Error storing detection: {e}")
    
    def get_recent_detections(self, hours: int = 24, min_confidence: float = 0.5) -> List[Dict]:
        """Get recent high-confidence detections"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        with self.lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute('''
                        SELECT ed.*, ta.memecoin_score, ta.sentiment
                        FROM early_detections ed
                        LEFT JOIN token_analysis ta ON ed.address = ta.address
                        WHERE ed.first_detected >= ? AND ed.confidence_score >= ?
                        ORDER BY ed.confidence_score DESC, ed.first_detected DESC
                        LIMIT 50
                    ''', (cutoff_time, min_confidence))
                    
                    columns = [desc[0] for desc in cursor.description]
                    return [dict(zip(columns, row)) for row in cursor.fetchall()]
                    
            except Exception as e:
                logger.error(f"Error fetching detections: {e}")
                return []

class EarlyMemecoindDetector:
    """Main early detection system"""
    
    def __init__(self):
        self.analyzer = TokenAnalyzer()
        self.dex_monitor = DEXMonitor()
        self.database = EarlyDetectionDatabase()
        self.running = False
        
    async def scan_for_early_memecoins(self) -> List[Dict]:
        """Single scan for early memecoins"""
        try:
            # Scan DEX APIs for new pairs
            new_tokens = await self.dex_monitor.scan_new_pairs()
            
            processed_tokens = []
            for token in new_tokens:
                # Analyze token for memecoin characteristics
                analysis = self.analyzer.analyze_token(token.name, token.symbol)
                
                # Update token with analysis results
                token.is_memecoin = analysis['memecoin_score'] > 0.5
                token.confidence_score = analysis['memecoin_score']
                
                # Determine risk level
                if analysis['risk_flags']:
                    token.risk_level = 'high'
                elif analysis['memecoin_score'] > 0.7:
                    token.risk_level = 'medium'
                else:
                    token.risk_level = 'low'
                
                # Store in database
                self.database.store_detection(token, analysis)
                
                # Add to results if high confidence
                if token.confidence_score > 0.4:
                    processed_tokens.append(token.to_dict())
            
            return processed_tokens
            
        except Exception as e:
            logger.error(f"Error in early detection scan: {e}")
            return []
    
    def get_recent_discoveries(self, hours: int = 24) -> List[Dict]:
        """Get recent early discoveries"""
        return self.database.get_recent_detections(hours=hours)
    
    async def start_continuous_monitoring(self):
        """Start continuous monitoring (for background tasks)"""
        self.running = True
        
        while self.running:
            try:
                await self.scan_for_early_memecoins()
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in continuous monitoring: {e}")
                await asyncio.sleep(30)
    
    def stop_monitoring(self):
        """Stop continuous monitoring"""
        self.running = False

# Global instance for use in handlers
early_detector = EarlyMemecoindDetector()

# Utility functions for backward compatibility
def scan_early_memecoins(hours_back: int = 6) -> List[Dict]:
    """Scan for early memecoins - synchronous wrapper"""
    try:
        # Run async scan
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        new_detections = loop.run_until_complete(early_detector.scan_for_early_memecoins())
        recent_detections = early_detector.get_recent_discoveries(hours=hours_back)
        
        # Combine and deduplicate
        all_detections = new_detections + recent_detections
        seen_addresses = set()
        unique_detections = []
        
        for detection in all_detections:
            addr = detection.get('address', '')
            if addr and addr not in seen_addresses:
                seen_addresses.add(addr)
                unique_detections.append(detection)
        
        # Sort by confidence score
        unique_detections.sort(key=lambda x: x.get('confidence_score', 0), reverse=True)
        
        return unique_detections[:20]  # Return top 20
        
    except Exception as e:
        logger.error(f"Error in scan_early_memecoins: {e}")
        return []

def get_memecoin_analysis(address: str) -> Optional[Dict]:
    """Get detailed analysis for specific token"""
    try:
        detections = early_detector.database.get_recent_detections(hours=168)  # 1 week
        
        for detection in detections:
            if detection.get('address') == address:
                return detection
        
        return None
        
    except Exception as e:
        logger.error(f"Error getting token analysis: {e}")
        return None

# Test function
def test_early_detection() -> Dict:
    """Test early detection system"""
    try:
        # Test database connection
        early_detector.database._init_database()
        
        # Test analyzer
        test_analysis = early_detector.analyzer.analyze_token("DogeCoin", "DOGE", "Much wow very moon")
        
        return {
            'status': 'working',
            'database_connected': True,
            'analyzer_working': True,
            'spacy_available': SPACY_AVAILABLE,
            'test_analysis': test_analysis
        }
        
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'database_connected': False,
            'analyzer_working': False,
            'spacy_available': SPACY_AVAILABLE
        }