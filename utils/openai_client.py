import os
import asyncio
import logging
from typing import Optional, Dict, List
import openai
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

class OpenAIClient:
    """OpenAI/OpenRouter API client with conversation context management"""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize OpenAI/OpenRouter client"""
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OpenAI API key not found. Set OPENAI_API_KEY environment variable.")
        
        # Determine which API to use based on key format
        base_url = None
        if self.api_key.startswith('sk-or-v1'):
            # OpenRouter API
            base_url = "https://openrouter.ai/api/v1"
            logger.info("Using OpenRouter API")
        else:
            # OpenAI API
            base_url = "https://api.openai.com/v1"
            logger.info("Using OpenAI API")
        
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=base_url)
        self.model = os.getenv('OPENAI_MODEL', 'gpt-3.5-turbo')
        self.max_tokens = int(os.getenv('OPENAI_MAX_TOKENS', '1000'))
        self.temperature = float(os.getenv('OPENAI_TEMPERATURE', '0.7'))
        
        # Conversation context storage (in production, use Redis or database)
        self.conversation_contexts = {}
        
        # System prompt for TonGPT
        self.system_prompt = """
You are TonGPT, an AI assistant specialized in TON blockchain memecoins analysis. 
Your expertise includes:

1. TON memecoin analysis and trends
2. Market sentiment analysis  
3. Technical analysis of memecoin projects
4. Risk assessment for memecoin investments
5. Community and social metrics analysis

Guidelines:
- Focus ONLY on TON blockchain memecoins
- Avoid discussing major cryptocurrencies (BTC, ETH, etc.)
- Provide balanced analysis with risks and opportunities
- Be concise but informative
- Use emojis sparingly and appropriately
- Never provide financial advice, only educational analysis
- Always mention that crypto investments are risky

Keep responses under 500 words unless specifically asked for detailed analysis.
        """.strip()
    
    async def get_chat_response(self, user_id: int, message: str, context: Optional[List[Dict]] = None) -> str:
        """Get AI response for user message with context"""
        try:
            # Build conversation messages
            messages = [{"role": "system", "content": self.system_prompt}]
            
            # Add conversation context if provided
            if context:
                messages.extend(context[-10:])  # Keep last 10 messages for context
            
            # Add current user message
            messages.append({"role": "user", "content": message})
            
            # Get response from OpenAI
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                timeout=30.0
            )
            
            ai_response = response.choices[0].message.content.strip()
            
            # Store conversation context (in production, use persistent storage)
            if user_id not in self.conversation_contexts:
                self.conversation_contexts[user_id] = []
            
            self.conversation_contexts[user_id].extend([
                {"role": "user", "content": message},
                {"role": "assistant", "content": ai_response}
            ])
            
            # Keep only last 20 messages per user
            if len(self.conversation_contexts[user_id]) > 20:
                self.conversation_contexts[user_id] = self.conversation_contexts[user_id][-20:]
            
            return ai_response
            
        except Exception as e:
            logger.error(f"OpenAI API error for user {user_id}: {e}")
            return "I'm experiencing technical difficulties right now. Please try again in a moment! 🤖"
    
    async def analyze_memecoin(self, token_data: Dict) -> str:
        """Analyze memecoin data and provide insights"""
        try:
            analysis_prompt = f"""
Analyze this TON memecoin data and provide insights:

Token: {token_data.get('name', 'Unknown')} ({token_data.get('symbol', 'N/A')})
Price: ${token_data.get('price', 'N/A')}
24h Change: {token_data.get('price_change_24h', 'N/A')}%
Volume: ${token_data.get('volume_24h', 'N/A')}
Market Cap: ${token_data.get('market_cap', 'N/A')}

Provide a brief analysis covering:
1. Price movement assessment
2. Volume analysis
3. Risk factors
4. Key observations

Keep response under 300 words.
            """
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": analysis_prompt}
                ],
                max_tokens=400,
                temperature=0.6
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"Memecoin analysis error: {e}")
            return "Unable to analyze this memecoin at the moment. Please try again later."
    
    async def get_market_summary(self, memecoins_data: List[Dict]) -> str:
        """Generate market summary from multiple memecoins"""
        try:
            # Prepare market data summary
            total_tokens = len(memecoins_data)
            if total_tokens == 0:
                return "No memecoin data available for analysis."
            
            # Calculate basic metrics
            positive_changes = sum(1 for token in memecoins_data 
                                 if token.get('price_change_24h', 0) > 0)
            negative_changes = total_tokens - positive_changes
            
            summary_prompt = f"""
Analyze this TON memecoin market overview:

Total Memecoins Tracked: {total_tokens}
Tokens with Positive 24h Change: {positive_changes}
Tokens with Negative 24h Change: {negative_changes}

Top Performers (by volume):
{self._format_top_performers(memecoins_data[:5])}

Provide a brief market summary covering:
1. Overall market sentiment
2. Notable trends
3. Risk assessment
4. Key takeaways

Keep response under 400 words.
            """
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": summary_prompt}
                ],
                max_tokens=500,
                temperature=0.7
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"Market summary error: {e}")
            return "Unable to generate market summary at the moment."
    
    def _format_top_performers(self, tokens: List[Dict]) -> str:
        """Format top performing tokens for analysis"""
        formatted = []
        for i, token in enumerate(tokens, 1):
            name = token.get('name', 'Unknown')
            symbol = token.get('symbol', 'N/A')
            change = token.get('price_change_24h', 'N/A')
            volume = token.get('volume_24h', 'N/A')
            
            formatted.append(f"{i}. {name} ({symbol}) - {change}% change, ${volume} volume")
        
        return "\n".join(formatted) if formatted else "No top performers data available"
    
    async def clear_context(self, user_id: int) -> bool:
        """Clear conversation context for user"""
        try:
            if user_id in self.conversation_contexts:
                del self.conversation_contexts[user_id]
            return True
        except Exception as e:
            logger.error(f"Error clearing context for user {user_id}: {e}")
            return False
    
    async def get_context(self, user_id: int) -> List[Dict]:
        """Get conversation context for user"""
        return self.conversation_contexts.get(user_id, [])
    
    async def health_check(self) -> bool:
        """Check if OpenAI API is accessible"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10,
                timeout=10.0
            )
            return bool(response.choices)
        except Exception as e:
            logger.error(f"OpenAI health check failed: {e}")
            return False