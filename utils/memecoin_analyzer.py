import requests
import logging
import os
import time
import re
import json
import asyncio
import aiohttp
import sqlite3
import threading
from typing import Dict, List, Optional, Set, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from collections import defaultdict, Counter, deque
import hashlib
import numpy as np
from urllib.parse import urljoin
import backoff

logger = logging.getLogger(__name__)

@dataclass
class MemecoinIntelligence:
    """Comprehensive memecoin intelligence data structure"""
    # Basic token info
    name: str
    symbol: str
    address: str
    price: float = 0.0
    market_cap: float = 0.0
    volume_24h: float = 0.0
    
    # Discovery metadata
    discovered_at: str = ""
    launch_detected_at: str = ""
    discovery_source: str = ""
    age_minutes: int = 0
    
    # Memecoin scoring (0-100)
    memecoin_score: float = 0.0
    viral_potential: float = 0.0
    risk_score: float = 0.0
    
    # Pattern analysis
    name_pattern_score: float = 0.0
    ticker_pattern_score: float = 0.0
    supply_pattern_score: float = 0.0
    community_pattern_score: float = 0.0
    
    # Community intelligence
    telegram_channels: List[str] = field(default_factory=list)
    telegram_members: int = 0
    member_growth_rate: float = 0.0
    organic_activity_score: float = 0.0
    bot_activity_percentage: float = 0.0
    
    # Blockchain metrics
    holder_count: int = 0
    holder_growth_rate: float = 0.0
    whale_activity: float = 0.0
    liquidity_usd: float = 0.0
    initial_liquidity: float = 0.0
    
    # Trading intelligence
    volume_spike_score: float = 0.0
    price_momentum: float = 0.0
    buy_pressure_ratio: float = 0.0
    early_buyer_profit: float = 0.0
    
    # Risk flags
    honeypot_risk: bool = False
    rug_pull_indicators: List[str] = field(default_factory=list)
    scam_patterns: List[str] = field(default_factory=list)
    
    # Social signals
    mention_velocity: float = 0.0
    influencer_mentions: int = 0
    coordinated_campaign: bool = False
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for API responses"""
        return {
            'name': self.name,
            'symbol': self.symbol,
            'address': self.address,
            'price': self.price,
            'market_cap': self.market_cap,
            'volume_24h': self.volume_24h,
            'discovered_at': self.discovered_at,
            'age_minutes': self.age_minutes,
            'memecoin_score': self.memecoin_score,
            'viral_potential': self.viral_potential,
            'risk_score': self.risk_score,
            'telegram_members': self.telegram_members,
            'holder_count': self.holder_count,
            'liquidity_usd': self.liquidity_usd,
            'whale_activity': self.whale_activity,
            'risk_flags': {
                'honeypot_risk': self.honeypot_risk,
                'rug_pull_indicators': self.rug_pull_indicators,
                'scam_patterns': self.scam_patterns
            },
            'intelligence_summary': self._generate_summary()
        }
    
    def _generate_summary(self) -> str:
        """Generate human-readable intelligence summary"""
        risk_level = "HIGH" if self.risk_score > 70 else "MEDIUM" if self.risk_score > 40 else "LOW"
        viral_level = "HIGH" if self.viral_potential > 70 else "MEDIUM" if self.viral_potential > 40 else "LOW"
        
        return f"Score: {self.memecoin_score:.0f}/100 | Viral: {viral_level} | Risk: {risk_level} | Age: {self.age_minutes}min"

class MemecoinPatternRecognizer:
    """Advanced pattern recognition for memecoin characteristics"""
    
    def __init__(self):
        self._setup_patterns()
        
    def _setup_patterns(self):
        """Setup memecoin recognition patterns"""
        
        # Memecoin name patterns (weighted by frequency and success)
        self.name_patterns = {
            'animals': {
                'patterns': [r'\b(dog|cat|frog|fish|duck|bear|bull|cow|pig|sheep|goat|horse|bird|eagle|hawk|owl|fox|wolf|deer|rabbit|hamster|mouse|rat|turtle|snake|lizard|monkey|ape|lion|tiger|elephant|whale|dolphin|shark|octopus)\b'],
                'weight': 0.25,
                'examples': ['DOGS', 'FISH', 'HAMSTER']
            },
            'meme_references': {
                'patterns': [r'\b(pepe|wojak|chad|karen|boomer|zoomer|moon|rocket|diamond|paper|hands|hodl|wagmi|ngmi|cope|hopium|copium)\b'],
                'weight': 0.20,
                'examples': ['PEPE', 'CHAD', 'MOON']
            },
            'internet_culture': {
                'patterns': [r'\b(meme|viral|trend|based|cringe|sus|cap|no\s?cap|lit|fire|flex|simp|stan|salty|toxic|mid|lowkey|highkey|periodt)\b'],
                'weight': 0.15,
                'examples': ['VIRAL', 'BASED', 'FIRE']
            },
            'diminutives': {
                'patterns': [r'\b\w+(ito|inho|ie|y|ey|er)$', r'\b(little|mini|baby|tiny|small|micro)\w*'],
                'weight': 0.10,
                'examples': ['DOGITO', 'BABYDOGE', 'MINI']
            },
            'action_words': {
                'patterns': [r'\b(pump|dump|moon|rocket|fly|run|jump|dance|party|celebrate|win|lose|buy|sell|hold|stake|farm|mine)\b'],
                'weight': 0.10,
                'examples': ['PUMP', 'MOON', 'ROCKET']
            }
        }
        
        # Ticker symbol patterns
        self.ticker_patterns = {
            'length': {
                '3_4_chars': {'weight': 0.30, 'regex': r'^[A-Z]{3,4}$'},
                '5_6_chars': {'weight': 0.20, 'regex': r'^[A-Z]{5,6}$'},
                'longer': {'weight': 0.10, 'regex': r'^[A-Z]{7,}$'}
            },
            'repetition': {
                'double_letters': {'weight': 0.15, 'regex': r'([A-Z])\1'},
                'triple_letters': {'weight': 0.10, 'regex': r'([A-Z])\1\1'}
            },
            'ending_patterns': {
                'coin_suffix': {'weight': 0.15, 'regex': r'COIN$'},
                'token_suffix': {'weight': 0.10, 'regex': r'TOKEN$'},
                'number_suffix': {'weight': 0.20, 'regex': r'\d$'}
            }
        }
        
        # Supply characteristics typical of memecoins
        self.supply_patterns = {
            'large_supply': (1e12, 1e18),  # 1T to 1Q tokens
            'round_numbers': [1e6, 1e9, 1e12, 1e15, 1e18],
            'meme_numbers': [420, 69, 1337, 8008, 80085, 42069]
        }

    def analyze_memecoin_patterns(self, name: str, symbol: str, total_supply: float = None) -> Dict[str, float]:
        """Analyze memecoin patterns and return scores"""
        
        scores = {
            'name_pattern_score': self._analyze_name_patterns(name.lower()),
            'ticker_pattern_score': self._analyze_ticker_patterns(symbol.upper()),
            'supply_pattern_score': self._analyze_supply_patterns(total_supply) if total_supply else 0.0
        }
        
        return scores
    
    def _analyze_name_patterns(self, name: str) -> float:
        """Analyze name for memecoin patterns"""
        total_score = 0.0
        
        for category, data in self.name_patterns.items():
            for pattern in data['patterns']:
                if re.search(pattern, name, re.IGNORECASE):
                    total_score += data['weight']
                    break  # Only count once per category
        
        return min(total_score, 1.0)  # Cap at 1.0
    
    def _analyze_ticker_patterns(self, symbol: str) -> float:
        """Analyze ticker symbol for memecoin patterns"""
        total_score = 0.0
        
        # Length analysis
        for pattern_name, pattern_data in self.ticker_patterns['length'].items():
            if re.match(pattern_data['regex'], symbol):
                total_score += pattern_data['weight']
                break
        
        # Repetition analysis
        for pattern_name, pattern_data in self.ticker_patterns['repetition'].items():
            if re.search(pattern_data['regex'], symbol):
                total_score += pattern_data['weight']
        
        # Ending patterns
        for pattern_name, pattern_data in self.ticker_patterns['ending_patterns'].items():
            if re.search(pattern_data['regex'], symbol):
                total_score += pattern_data['weight']
        
        return min(total_score, 1.0)
    
    def _analyze_supply_patterns(self, total_supply: float) -> float:
        """Analyze supply characteristics"""
        if not total_supply or total_supply <= 0:
            return 0.0
        
        score = 0.0
        
        # Check if supply is in memecoin range
        min_supply, max_supply = self.supply_patterns['large_supply']
        if min_supply <= total_supply <= max_supply:
            score += 0.4
        
        # Check for round numbers
        for round_num in self.supply_patterns['round_numbers']:
            if abs(total_supply - round_num) / round_num < 0.1:  # Within 10%
                score += 0.3
                break
        
        # Check for meme numbers
        supply_str = str(int(total_supply))
        for meme_num in self.supply_patterns['meme_numbers']:
            if str(meme_num) in supply_str:
                score += 0.3
                break
        
        return min(score, 1.0)

class MemecoinAnalyzer:
    """Main analyzer class for memecoin intelligence"""
    
    def __init__(self):
        self.pattern_recognizer = MemecoinPatternRecognizer()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def analyze_token(self, symbol: str) -> Optional[Dict]:
        """Analyze a token by symbol - main entry point for bot"""
        try:
            # Get token data from DEX Screener
            token_data = self._fetch_token_data(symbol)
            if not token_data:
                return None
            
            # Perform analysis
            analysis = self._perform_analysis(token_data)
            return analysis
            
        except Exception as e:
            logger.error(f"Token analysis failed for {symbol}: {e}")
            return None
    
    def _fetch_token_data(self, symbol: str) -> Optional[Dict]:
        """Fetch token data from DEX Screener API"""
        try:
            url = f"https://api.dexscreener.com/latest/dex/search/?q={symbol}"
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                pairs = data.get('pairs', [])
                
                # Find TON pairs
                ton_pairs = [p for p in pairs if p.get('chainId') == 'ton']
                if ton_pairs:
                    return ton_pairs[0]  # Return first TON pair
                elif pairs:
                    return pairs[0]  # Fallback to any pair
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to fetch data for {symbol}: {e}")
            return None
    
    def _perform_analysis(self, token_data: Dict) -> Dict:
        """Perform comprehensive token analysis"""
        try:
            base_token = token_data.get('baseToken', {})
            name = base_token.get('name', '')
            symbol = base_token.get('symbol', '')
            address = base_token.get('address', '')
            
            # Basic metrics
            price = float(token_data.get('priceUsd', 0))
            volume_24h = float(token_data.get('volume', {}).get('h24', 0))
            liquidity_usd = float(token_data.get('liquidity', {}).get('usd', 0))
            
            # Calculate age
            created_at = token_data.get('pairCreatedAt', 0)
            age_minutes = 0
            if created_at:
                age_minutes = (time.time() * 1000 - created_at) / (1000 * 60)
            
            # Pattern analysis
            pattern_scores = self.pattern_recognizer.analyze_memecoin_patterns(name, symbol)
            
            # Calculate scores
            memecoin_score = self._calculate_memecoin_score(
                pattern_scores, volume_24h, liquidity_usd, age_minutes
            )
            
            viral_potential = self._calculate_viral_potential(
                pattern_scores, volume_24h, age_minutes
            )
            
            risk_score = self._calculate_risk_score(
                liquidity_usd, age_minutes, volume_24h
            )
            
            # Build result
            result = {
                'name': name,
                'symbol': symbol,
                'address': address,
                'price': price,
                'volume_24h': volume_24h,
                'liquidity_usd': liquidity_usd,
                'age_minutes': int(age_minutes),
                'memecoin_score': round(memecoin_score, 1),
                'viral_potential': round(viral_potential, 1),
                'risk_score': round(risk_score, 1),
                'pattern_scores': pattern_scores,
                'analysis_time': datetime.now().isoformat(),
                'summary': self._generate_summary(memecoin_score, viral_potential, risk_score)
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            return {}
    
    def _calculate_memecoin_score(self, pattern_scores: Dict, volume: float, liquidity: float, age_minutes: float) -> float:
        """Calculate overall memecoin score"""
        
        # Pattern score (40%)
        pattern_score = (
            pattern_scores['name_pattern_score'] * 25 +
            pattern_scores['ticker_pattern_score'] * 15
        )
        
        # Volume score (30%)
        volume_score = 0
        if volume > 100000:
            volume_score = 30
        elif volume > 50000:
            volume_score = 25
        elif volume > 10000:
            volume_score = 20
        elif volume > 1000:
            volume_score = 15
        elif volume > 100:
            volume_score = 10
        
        # Liquidity score (20%)
        liquidity_score = 0
        if liquidity > 100000:
            liquidity_score = 20
        elif liquidity > 50000:
            liquidity_score = 15
        elif liquidity > 25000:
            liquidity_score = 12
        elif liquidity > 10000:
            liquidity_score = 8
        elif liquidity > 5000:
            liquidity_score = 5
        
        # Age bonus (10%)
        age_score = 0
        if age_minutes <= 60:
            age_score = 10
        elif age_minutes <= 360:
            age_score = 7
        elif age_minutes <= 1440:
            age_score = 4
        
        total = pattern_score + volume_score + liquidity_score + age_score
        return min(100.0, max(0.0, total))
    
    def _calculate_viral_potential(self, pattern_scores: Dict, volume: float, age_minutes: float) -> float:
        """Calculate viral potential score"""
        
        score = 0
        
        # Pattern memorability (40%)
        name_score = pattern_scores['name_pattern_score'] * 40
        score += name_score
        
        # Early momentum (35%)
        if age_minutes <= 120 and volume > 10000:
            score += 35
        elif age_minutes <= 360 and volume > 5000:
            score += 25
        elif volume > 1000:
            score += 15
        
        # Ticker catchiness (25%)
        ticker_score = pattern_scores['ticker_pattern_score'] * 25
        score += ticker_score
        
        return min(100.0, score)
    
    def _calculate_risk_score(self, liquidity: float, age_minutes: float, volume: float) -> float:
        """Calculate risk score (higher = more risky)"""
        
        risk = 0
        
        # Liquidity risk (40%)
        if liquidity < 1000:
            risk += 40
        elif liquidity < 5000:
            risk += 30
        elif liquidity < 25000:
            risk += 15
        elif liquidity < 50000:
            risk += 5
        
        # Age risk (30%)
        if age_minutes < 30:
            risk += 30
        elif age_minutes < 120:
            risk += 20
        elif age_minutes < 360:
            risk += 10
        
        # Volume anomaly risk (30%)
        if volume > 0 and liquidity > 0:
            volume_to_liquidity = volume / liquidity
            if volume_to_liquidity > 10:  # Suspicious volume
                risk += 30
            elif volume_to_liquidity > 5:
                risk += 15
        else:
            risk += 20  # No volume data
        
        return min(100.0, risk)
    
    def _generate_summary(self, memecoin_score: float, viral_potential: float, risk_score: float) -> str:
        """Generate human-readable summary"""
        
        # Score interpretation
        if memecoin_score >= 80:
            score_text = "EXCELLENT"
        elif memecoin_score >= 60:
            score_text = "GOOD"
        elif memecoin_score >= 40:
            score_text = "MODERATE"
        else:
            score_text = "LOW"
        
        # Risk interpretation
        if risk_score >= 70:
            risk_text = "HIGH RISK"
        elif risk_score >= 40:
            risk_text = "MEDIUM RISK"
        else:
            risk_text = "LOW RISK"
        
        # Viral interpretation
        if viral_potential >= 70:
            viral_text = "HIGH VIRAL POTENTIAL"
        elif viral_potential >= 40:
            viral_text = "MODERATE VIRAL POTENTIAL"
        else:
            viral_text = "LIMITED VIRAL POTENTIAL"
        
        return f"{score_text} memecoin | {viral_text} | {risk_text}"

# Utility functions for easy bot integration

def analyze_memecoin(symbol: str) -> Optional[Dict]:
    """Quick analysis function for bot commands"""
    analyzer = MemecoinAnalyzer()
    return analyzer.analyze_token(symbol)

def is_memecoin_pattern(name: str, symbol: str) -> bool:
    """Quick check if token matches memecoin patterns"""
    recognizer = MemecoinPatternRecognizer()
    scores = recognizer.analyze_memecoin_patterns(name, symbol)
    
    combined_score = (scores['name_pattern_score'] + scores['ticker_pattern_score']) / 2
    return combined_score > 0.3

def get_memecoin_score(token_data: Dict) -> float:
    """Get memecoin score from token data"""
    analyzer = MemecoinAnalyzer()
    analysis = analyzer._perform_analysis(token_data)
    return analysis.get('memecoin_score', 0.0)

# For backward compatibility
def get_ton_price():
    """Get current TON price"""
    try:
        response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd")
        data = response.json()
        return data.get('the-open-network', {}).get('usd', 0)
    except:
        return 0

def get_token_info(symbol: str):
    """Get basic token info"""
    return analyze_memecoin(symbol)