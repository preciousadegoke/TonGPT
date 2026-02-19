import asyncio
import aiohttp
import requests
import logging
import time
import json
from typing import Dict, List, Optional, Union, Any, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import backoff
from enum import Enum

logger = logging.getLogger(__name__)

class DataSource(Enum):
    """Data source identifiers"""
    DEXSCREENER = "dexscreener"
    TONAPI = "tonapi"
    COINGECKO = "coingecko"
    GECKOTERMINAL = "geckoterminal"
    TONCENTER = "toncenter"

@dataclass
class TokenData:
    """Clean token data structure"""
    address: str
    name: str
    symbol: str
    decimals: int
    price_usd: float = 0.0
    price_ton: float = 0.0
    market_cap: float = 0.0
    volume_24h: float = 0.0
    holders: int = 0
    liquidity_usd: float = 0.0
    price_change_24h: float = 0.0
    created_at: Optional[str] = None
    verified: bool = False
    source: str = "unknown"
    dex: str = "STON.fi"
    last_updated: Optional[str] = None

    def __post_init__(self):
        """Validate data after initialization"""
        self.last_updated = self.last_updated or datetime.now().isoformat()
        
        # Ensure numeric fields are properly typed
        numeric_fields = ['price_usd', 'price_ton', 'market_cap', 'volume_24h', 'liquidity_usd', 'price_change_24h']
        for field in numeric_fields:
            value = getattr(self, field)
            try:
                setattr(self, field, float(value) if value is not None else 0.0)
            except (ValueError, TypeError):
                setattr(self, field, 0.0)

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)

class TONDataFetcher:
    """Production TON blockchain data fetcher - live data only"""
    
    def __init__(self):
        # HTTP session with connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'TonGPT-Bot/2.0 (https://github.com/tongpt)',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9'
        })
        
        # API endpoints configuration
        self.api_endpoints = {
            DataSource.DEXSCREENER: {
                'base_url': 'https://api.dexscreener.com/latest/dex',
                'timeout': 15,
                'priority': 1
            },
            DataSource.COINGECKO: {
                'base_url': 'https://api.coingecko.com/api/v3',
                'timeout': 12,
                'priority': 2
            },
            DataSource.TONAPI: {
                'base_url': 'https://tonapi.io/v2',
                'timeout': 10,
                'priority': 3
            },
            DataSource.GECKOTERMINAL: {
                'base_url': 'https://api.geckoterminal.com/api/v2',
                'timeout': 10,
                'priority': 4
            },
            DataSource.TONCENTER: {
                'base_url': 'https://toncenter.com/api/v2',
                'timeout': 8,
                'priority': 5
            }
        }
        
        # Simple memory cache with TTL
        self.cache = {}
        self.cache_ttl = {}
        self.default_cache_duration = 60  # 1 minute for most data
        self.price_cache_duration = 30    # 30 seconds for price data
        
        # Rate limiting tracking
        self.request_timestamps = {}
        self.rate_limit_window = 60
        self.max_requests_per_minute = 120

    def _is_rate_limited(self, source: str) -> bool:
        """Check rate limiting status"""
        now = time.time()
        if source not in self.request_timestamps:
            self.request_timestamps[source] = []
        
        # Clean old timestamps
        self.request_timestamps[source] = [
            ts for ts in self.request_timestamps[source] 
            if now - ts < self.rate_limit_window
        ]
        
        return len(self.request_timestamps[source]) >= self.max_requests_per_minute

    def _record_request(self, source: str):
        """Record request for rate limiting"""
        if source not in self.request_timestamps:
            self.request_timestamps[source] = []
        self.request_timestamps[source].append(time.time())

    def _is_cache_valid(self, key: str) -> bool:
        """Check cache validity"""
        return (key in self.cache and 
                key in self.cache_ttl and 
                time.time() < self.cache_ttl[key])

    def _get_from_cache(self, key: str) -> Optional[Any]:
        """Get from cache if valid"""
        if self._is_cache_valid(key):
            return self.cache[key]
        return None

    def _set_cache(self, key: str, data: Any, duration: int = None):
        """Set cache with TTL"""
        duration = duration or self.default_cache_duration
        self.cache[key] = data
        self.cache_ttl[key] = time.time() + duration

    @backoff.on_exception(backoff.expo, requests.RequestException, max_tries=2, max_time=20)
    def _make_request(self, url: str, params: Dict = None, headers: Dict = None, timeout: int = 10) -> Optional[Dict]:
        """Make HTTP request with retry logic"""
        source = self._extract_source_from_url(url)
        
        if self._is_rate_limited(source):
            logger.warning(f"Rate limited for {source}")
            return None
        
        try:
            self._record_request(source)
            
            request_headers = self.session.headers.copy()
            if headers:
                request_headers.update(headers)
                
            response = self.session.get(url, params=params, headers=request_headers, timeout=timeout)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for {url}: {e}")
            return None

    def _extract_source_from_url(self, url: str) -> str:
        """Extract source identifier from URL"""
        for source in DataSource:
            if source.value in url.lower():
                return source.value
        return 'unknown'

    # === PRICE DATA METHODS ===
    
    def get_ton_price(self) -> Optional[float]:
        """Get current TON price - returns None if all sources fail"""
        cache_key = "ton_price"
        cached_price = self._get_from_cache(cache_key)
        if cached_price:
            return cached_price

        # Primary price sources
        price_sources = [
            {
                'name': 'CoinGecko',
                'url': 'https://api.coingecko.com/api/v3/simple/price',
                'params': {'ids': 'the-open-network', 'vs_currencies': 'usd'},
                'parser': lambda x: x.get('the-open-network', {}).get('usd')
            },
            {
                'name': 'DexScreener',
                'url': 'https://api.dexscreener.com/latest/dex/tokens/EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c',
                'params': {},
                'parser': lambda x: float(x.get('pairs', [{}])[0].get('priceUsd', 0)) if x.get('pairs') else None
            },
            {
                'name': 'GeckoTerminal',
                'url': 'https://api.geckoterminal.com/api/v2/simple/networks/ton/token_price/EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c',
                'params': {},
                'parser': lambda x: float(x.get('data', {}).get('attributes', {}).get('token_prices', {}).get('EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c', 0)) or None
            }
        ]

        for source in price_sources:
            try:
                data = self._make_request(source['url'], source['params'], timeout=8)
                if data:
                    price = source['parser'](data)
                    if price and price > 0:
                        self._set_cache(cache_key, price, self.price_cache_duration)
                        logger.info(f"TON price from {source['name']}: ${price:.4f}")
                        return price
            except Exception as e:
                logger.debug(f"{source['name']} price fetch failed: {e}")
                continue

        logger.error("All TON price sources failed")
        return None

    def get_ton_market_data(self) -> Optional[Dict]:
        """Get comprehensive TON market data"""
        cache_key = "ton_market_data"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return cached_data

        try:
            url = "https://api.coingecko.com/api/v3/coins/the-open-network"
            data = self._make_request(url, timeout=15)
            
            if not data or 'market_data' not in data:
                return None
            
            market_data = data.get('market_data', {})
            
            result = {
                'price_usd': market_data.get('current_price', {}).get('usd'),
                'market_cap': market_data.get('market_cap', {}).get('usd'),
                'volume_24h': market_data.get('total_volume', {}).get('usd'),
                'price_change_24h': market_data.get('price_change_percentage_24h'),
                'price_change_7d': market_data.get('price_change_percentage_7d'),
                'circulating_supply': market_data.get('circulating_supply'),
                'total_supply': market_data.get('total_supply'),
                'all_time_high': market_data.get('ath', {}).get('usd'),
                'all_time_low': market_data.get('atl', {}).get('usd'),
                'last_updated': datetime.now().isoformat(),
                'source': DataSource.COINGECKO.value
            }
            
            # Validate essential fields
            if result['price_usd'] and result['price_usd'] > 0:
                self._set_cache(cache_key, result, 120)
                return result
            
        except Exception as e:
            logger.error(f"Failed to get TON market data: {e}")

        return None

    # === TOKEN DISCOVERY METHODS ===
    
    def search_tokens(self, query: str, limit: int = 20) -> List[TokenData]:
        """Search for tokens - returns empty list if no results"""
        if not query or len(query.strip()) < 2:
            return []

        cache_key = f"search_{query.lower().strip()}_{limit}"
        cached_results = self._get_from_cache(cache_key)
        if cached_results:
            return [TokenData(**token) if isinstance(token, dict) else token for token in cached_results]

        try:
            url = "https://api.dexscreener.com/latest/dex/search"
            params = {'q': query.strip()}
            
            data = self._make_request(url, params, timeout=12)
            if not data or 'pairs' not in data:
                return []

            tokens = []
            seen_addresses = set()
            
            for pair in data['pairs']:
                # Filter for TON pairs only
                if pair.get('chainId') != 'ton':
                    continue
                
                base_token = pair.get('baseToken', {})
                address = base_token.get('address', '')
                
                if not address or address in seen_addresses:
                    continue
                
                # Skip if essential data is missing
                if not base_token.get('symbol') or not pair.get('priceUsd'):
                    continue
                
                seen_addresses.add(address)
                
                token = TokenData(
                    address=address,
                    name=base_token.get('name', ''),
                    symbol=base_token.get('symbol', ''),
                    decimals=int(base_token.get('decimals', 9)),
                    price_usd=pair.get('priceUsd', 0),
                    volume_24h=pair.get('volume', {}).get('h24', 0),
                    liquidity_usd=pair.get('liquidity', {}).get('usd', 0),
                    market_cap=pair.get('fdv', 0),
                    price_change_24h=pair.get('priceChange', {}).get('h24', 0),
                    created_at=self._format_timestamp(pair.get('pairCreatedAt')),
                    verified=bool(pair.get('info', {}).get('imageUrl')),
                    source=DataSource.DEXSCREENER.value,
                    dex=pair.get('dexId', 'STON.fi').upper()
                )
                
                tokens.append(token)
                
                if len(tokens) >= limit:
                    break

            if tokens:
                # Cache successful results
                self._set_cache(cache_key, [token.to_dict() for token in tokens], 180)
                
            return tokens

        except Exception as e:
            logger.error(f"Token search failed for '{query}': {e}")
            return []

    def get_token_info(self, identifier: str) -> Optional[TokenData]:
        """Get specific token info by address or symbol"""
        if not identifier:
            return None
            
        cache_key = f"token_{identifier.lower()}"
        cached_token = self._get_from_cache(cache_key)
        if cached_token:
            return TokenData(**cached_token) if isinstance(cached_token, dict) else cached_token

        # Check if it's an address or symbol
        if len(identifier) > 20 and identifier.startswith('EQ'):
            return self._get_token_by_address(identifier)
        else:
            # Search by symbol and return first match
            tokens = self.search_tokens(identifier, limit=5)
            if tokens:
                # Find exact symbol match first
                exact_match = next((t for t in tokens if t.symbol.upper() == identifier.upper()), None)
                token = exact_match or tokens[0]
                self._set_cache(cache_key, token.to_dict(), 300)
                return token
            
        return None

    def _get_token_by_address(self, address: str) -> Optional[TokenData]:
        """Get token info by contract address"""
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            data = self._make_request(url, timeout=10)
            
            if not data or 'pairs' not in data or not data['pairs']:
                return None
            
            pair = data['pairs'][0]
            base_token = pair.get('baseToken', {})
            
            # Validate essential data
            if not base_token.get('symbol') or not pair.get('priceUsd'):
                return None
            
            return TokenData(
                address=address,
                name=base_token.get('name', ''),
                symbol=base_token.get('symbol', ''),
                decimals=int(base_token.get('decimals', 9)),
                price_usd=pair.get('priceUsd', 0),
                volume_24h=pair.get('volume', {}).get('h24', 0),
                liquidity_usd=pair.get('liquidity', {}).get('usd', 0),
                market_cap=pair.get('fdv', 0),
                price_change_24h=pair.get('priceChange', {}).get('h24', 0),
                created_at=self._format_timestamp(pair.get('pairCreatedAt')),
                verified=bool(pair.get('info', {}).get('imageUrl')),
                source=DataSource.DEXSCREENER.value,
                dex=pair.get('dexId', 'STON.fi').upper()
            )

        except Exception as e:
            logger.error(f"Failed to get token by address {address}: {e}")
            return None

    def get_trending_tokens(self, limit: int = 15) -> List[TokenData]:
        """Get trending TON tokens"""
        cache_key = f"trending_{limit}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return [TokenData(**token) if isinstance(token, dict) else token for token in cached_data]

        try:
            # Get TON pairs from DexScreener - using search endpoint
            url = "https://api.dexscreener.com/latest/dex/search?q=TON"
            data = self._make_request(url, timeout=15)
            
            if not data or 'pairs' not in data:
                return []

            trending = []
            seen_addresses = set()
            
            # Sort by volume to get trending tokens
            pairs = sorted(data['pairs'], key=lambda x: x.get('volume', {}).get('h24', 0), reverse=True)
            
            for pair in pairs:
                base_token = pair.get('baseToken', {})
                address = base_token.get('address', '')
                
                if not address or address in seen_addresses:
                    continue
                
                # Skip if essential data missing
                if not base_token.get('symbol') or not pair.get('priceUsd'):
                    continue
                
                seen_addresses.add(address)
                
                token = TokenData(
                    address=address,
                    name=base_token.get('name', ''),
                    symbol=base_token.get('symbol', ''),
                    decimals=int(base_token.get('decimals', 9)),
                    price_usd=pair.get('priceUsd', 0),
                    volume_24h=pair.get('volume', {}).get('h24', 0),
                    liquidity_usd=pair.get('liquidity', {}).get('usd', 0),
                    market_cap=pair.get('fdv', 0),
                    price_change_24h=pair.get('priceChange', {}).get('h24', 0),
                    created_at=self._format_timestamp(pair.get('pairCreatedAt')),
                    verified=bool(pair.get('info', {}).get('imageUrl')),
                    source=DataSource.DEXSCREENER.value,
                    dex=pair.get('dexId', 'STON.fi').upper()
                )
                
                trending.append(token)
                
                if len(trending) >= limit:
                    break

            if trending:
                self._set_cache(cache_key, [token.to_dict() for token in trending], 180)
                
            return trending

        except Exception as e:
            logger.error(f"Failed to get trending tokens: {e}")
            return []

    def get_new_tokens(self, hours: int = 24, limit: int = 20) -> List[TokenData]:
        """Get newly created tokens in the last N hours"""
        try:
            url = "https://api.dexscreener.com/latest/dex/search?q=TON"
            data = self._make_request(url, timeout=15)
            
            if not data or 'pairs' not in data:
                return []

            cutoff_time = datetime.now() - timedelta(hours=hours)
            new_tokens = []
            seen_addresses = set()

            for pair in data['pairs']:
                created_at_timestamp = pair.get('pairCreatedAt')
                if not created_at_timestamp:
                    continue
                
                created_datetime = datetime.fromtimestamp(created_at_timestamp / 1000)
                
                if created_datetime <= cutoff_time:
                    continue
                
                base_token = pair.get('baseToken', {})
                address = base_token.get('address', '')
                
                if not address or address in seen_addresses:
                    continue
                
                # Skip if essential data missing
                if not base_token.get('symbol') or not pair.get('priceUsd'):
                    continue
                
                seen_addresses.add(address)
                
                token = TokenData(
                    address=address,
                    name=base_token.get('name', ''),
                    symbol=base_token.get('symbol', ''),
                    decimals=int(base_token.get('decimals', 9)),
                    price_usd=pair.get('priceUsd', 0),
                    volume_24h=pair.get('volume', {}).get('h24', 0),
                    liquidity_usd=pair.get('liquidity', {}).get('usd', 0),
                    market_cap=pair.get('fdv', 0),
                    price_change_24h=pair.get('priceChange', {}).get('h24', 0),
                    created_at=created_datetime.isoformat(),
                    source=DataSource.DEXSCREENER.value,
                    dex=pair.get('dexId', 'STON.fi').upper()
                )
                
                new_tokens.append(token)

            # Sort by creation time (newest first)
            new_tokens.sort(key=lambda x: x.created_at or '', reverse=True)
            return new_tokens[:limit]

        except Exception as e:
            logger.error(f"Failed to get new tokens: {e}")
            return []

    def _format_timestamp(self, timestamp) -> Optional[str]:
        """Format timestamp to ISO string"""
        if not timestamp:
            return None
        try:
            dt = datetime.fromtimestamp(timestamp / 1000)
            return dt.isoformat()
        except:
            return None

    def get_health_status(self) -> Dict:
        """Get system health status"""
        status = {
            'timestamp': datetime.now().isoformat(),
            'cache_stats': {},
            'api_status': {}
        }
        
        # Cache statistics
        for key, timestamp in self.cache_ttl.items():
            age = time.time() - (timestamp - self.default_cache_duration)
            status['cache_stats'][key] = {
                'age_seconds': int(age),
                'is_valid': self._is_cache_valid(key),
                'size': len(str(self.cache.get(key, '')))
            }
        
        # Test critical endpoints
        test_endpoints = [
            ('dexscreener', 'https://api.dexscreener.com/latest/dex/search?q=TON'),
            ('coingecko', 'https://api.coingecko.com/api/v3/ping')
        ]
        
        for name, url in test_endpoints:
            try:
                response = self.session.get(url, timeout=5)
                status['api_status'][name] = 'online' if response.status_code == 200 else f'error_{response.status_code}'
            except Exception as e:
                status['api_status'][name] = f'offline_{type(e).__name__}'
        
        return status

# === ASYNC VERSION ===

async def fetch_tokens_async(query: str, limit: int = 10) -> List[TokenData]:
    """Async version for better performance"""
    loop = asyncio.get_event_loop()
    fetcher = TONDataFetcher()
    return await loop.run_in_executor(None, fetcher.search_tokens, query, limit)

# === GLOBAL INSTANCE & CONVENIENCE FUNCTIONS ===

_ton_data_fetcher = TONDataFetcher()

def get_ton_price() -> Optional[float]:
    """Get current TON price"""
    return _ton_data_fetcher.get_ton_price()

def get_ton_market_data() -> Optional[Dict]:
    """Get TON market data"""
    return _ton_data_fetcher.get_ton_market_data()

def search_tokens(query: str, limit: int = 20) -> List[TokenData]:
    """Search for tokens"""
    return _ton_data_fetcher.search_tokens(query, limit)

def get_token_info(identifier: str) -> Optional[TokenData]:
    """Get token information"""
    return _ton_data_fetcher.get_token_info(identifier)

def get_trending_tokens(limit: int = 15) -> List[TokenData]:
    """Get trending tokens"""
    return _ton_data_fetcher.get_trending_tokens(limit)

def get_new_tokens(hours: int = 24, limit: int = 20) -> List[TokenData]:
    """Get new tokens"""
    return _ton_data_fetcher.get_new_tokens(hours, limit)

def get_health_status() -> Dict:
    """Get system health"""
    return _ton_data_fetcher.get_health_status()

# === CONTEXT GENERATION FOR GPT ===

def get_realtime_context(max_tokens: int = 50) -> str:
    """Get real-time context for GPT responses"""
    try:
        # Get current trending tokens
        trending = get_trending_tokens(15)
        
        if not trending:
            return "No live TON token data available at the moment."
        
        # Get TON price
        ton_price = get_ton_price()
        ton_price_str = f"${ton_price:.4f}" if ton_price else "N/A"
        
        context_lines = [
            f"LIVE TON DATA (${ton_price_str}):",
            ""
        ]
        
        # Categorize tokens by volume
        high_volume = [t for t in trending if t.volume_24h > 50000]
        medium_volume = [t for t in trending if 10000 <= t.volume_24h <= 50000]
        
        if high_volume:
            context_lines.append("HIGH VOLUME TOKENS:")
            for token in high_volume[:5]:
                context_lines.append(f"• ${token.symbol} - ${token.price_usd:.6f} (${token.volume_24h:,.0f} vol)")
        
        if medium_volume:
            context_lines.append("\nACTIVE TOKENS:")
            for token in medium_volume[:5]:
                context_lines.append(f"• ${token.symbol} - ${token.price_usd:.6f}")
        
        context_lines.extend([
            "",
            f"Total tracked: {len(trending)} active tokens",
            "Data source: Live DEX APIs"
        ])
        
        # Limit tokens to stay within context
        full_context = "\n".join(context_lines)
        if len(trending) > max_tokens:
            return full_context[:2000] + "\n... (truncated for length)"
        
        return full_context
        
    except Exception as e:
        logger.error(f"Failed to generate realtime context: {e}")
        return "Error retrieving live TON data."

if __name__ == "__main__":
    # Test the fetcher
    fetcher = TONDataFetcher()
    
    print("Testing TON Data Fetcher...")
    
    # Test TON price
    price = fetcher.get_ton_price()
    print(f"TON Price: ${price}" if price else "TON Price: Failed to fetch")
    
    # Test token search
    tokens = fetcher.search_tokens("DOGS", 3)
    print(f"Found {len(tokens)} DOGS tokens")
    
    # Test trending
    trending = fetcher.get_trending_tokens(5)
    print(f"Trending tokens: {len(trending)}")
    
    # Test context generation
    context = get_realtime_context()
    print(f"Context length: {len(context)} chars")
    
    print("Tests completed!")