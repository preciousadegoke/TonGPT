import asyncio
import logging
import json
import os
from decimal import Decimal
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Any

# Handle telegram imports with better error handling
try:
    from telegram import Bot
    from telegram.error import TelegramError, BadRequest, Forbidden, NetworkError
    TELEGRAM_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Telegram bot library not installed: {e}")
    print("Install with: pip install python-telegram-bot==20.7")
    TELEGRAM_AVAILABLE = False
    
    # Mock classes for development without telegram
    class Bot:
        def __init__(self, token):
            self.token = token
        
        async def send_message(self, chat_id, text, **kwargs):
            print(f"Mock send to {chat_id}: {text}")
    
    class TelegramError(Exception):
        pass
    
    BadRequest = Forbidden = NetworkError = TelegramError

# Optional: Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self):
        # Telegram bot token from environment variable
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not self.bot_token and TELEGRAM_AVAILABLE:
            logger.warning("TELEGRAM_BOT_TOKEN environment variable not found")
            # For development, you can set a default token here
            # self.bot_token = "YOUR_BOT_TOKEN_HERE"
        
        self.bot = None
        if self.bot_token and TELEGRAM_AVAILABLE:
            try:
                self.bot = Bot(token=self.bot_token)
                logger.info("Telegram bot initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Telegram bot: {e}")
        else:
            logger.warning("Running in mock mode - notifications will be logged only")
        
        # Initialize database for user preferences and notifications
        self.init_database()
    
    def init_database(self):
        """Initialize SQLite database for notification settings"""
        try:
            conn = sqlite3.connect('notifications.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_notifications (
                    user_id TEXT,
                    notification_type TEXT,
                    enabled BOOLEAN DEFAULT 1,
                    settings TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, notification_type)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS followed_wallets (
                    user_id TEXT,
                    wallet_address TEXT,
                    wallet_name TEXT,
                    min_amount REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, wallet_address)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notification_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    notification_type TEXT,
                    message TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    success BOOLEAN
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info("Database initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    def format_transaction(self, transaction: Dict) -> str:
        """Format transaction data for display"""
        try:
            # Extract transaction details with safe defaults
            tx_hash = transaction.get('hash', 'N/A')
            from_addr = transaction.get('from_address', 'Unknown')
            to_addr = transaction.get('to_address', 'Unknown')
            amount = transaction.get('amount', 0)
            token = transaction.get('token', 'TON')
            timestamp = transaction.get('timestamp', datetime.utcnow())
            tx_type = transaction.get('type', 'transfer')
            
            # Format amount with proper decimals
            if isinstance(amount, (int, float, Decimal)):
                if amount >= 1000000:
                    formatted_amount = f"{amount/1000000:.2f}M"
                elif amount >= 1000:
                    formatted_amount = f"{amount/1000:.2f}K"
                else:
                    formatted_amount = f"{amount:.4f}"
            else:
                formatted_amount = str(amount)
            
            # Format addresses (show first 6 and last 4 characters)
            def format_address(addr):
                if len(str(addr)) > 10:
                    addr_str = str(addr)
                    return f"{addr_str[:6]}...{addr_str[-4:]}"
                return str(addr)
            
            from_formatted = format_address(from_addr)
            to_formatted = format_address(to_addr)
            
            # Format timestamp
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except ValueError:
                    timestamp = datetime.utcnow()
            
            time_str = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
            
            # Create transaction message
            message = f"""
<b>💰 Transaction Details</b>

<b>Type:</b> {tx_type.upper()}
<b>Amount:</b> {formatted_amount} {token}
<b>From:</b> <code>{from_formatted}</code>
<b>To:</b> <code>{to_formatted}</code>
<b>Time:</b> {time_str}
<b>Hash:</b> <code>{tx_hash[:16] if len(str(tx_hash)) > 16 else tx_hash}...</code>

<a href="https://tonscan.org/tx/{tx_hash}">🔍 View on TONScan</a>
            """.strip()
            
            return message
            
        except Exception as e:
            logger.error(f"Error formatting transaction: {e}")
            return f"<b>Transaction detected</b>\nAmount: {transaction.get('amount', 'N/A')} {transaction.get('token', 'TON')}"
    
    def format_price_alert(self, price_data: Dict) -> str:
        """Format price alert data"""
        try:
            symbol = price_data.get('symbol', 'TON')
            current_price = price_data.get('current_price', 0)
            price_change = price_data.get('price_change_24h', 0)
            price_change_percent = price_data.get('price_change_percentage_24h', 0)
            
            # Format price change with emoji
            if price_change >= 0:
                change_emoji = "📈"
                change_color = "🟢"
            else:
                change_emoji = "📉"
                change_color = "🔴"
            
            message = f"""
<b>{change_emoji} PRICE ALERT {change_emoji}</b>

<b>{symbol} Price Update</b>
<b>Current Price:</b> ${current_price:.6f}
<b>24h Change:</b> {change_color} ${price_change:+.6f} ({price_change_percent:+.2f}%)

<i>Alert triggered at {datetime.utcnow().strftime('%H:%M:%S UTC')}</i>
            """.strip()
            
            return message
            
        except Exception as e:
            logger.error(f"Error formatting price alert: {e}")
            return f"<b>Price Alert</b>\n{symbol}: ${price_data.get('current_price', 'N/A')}"
    
    async def send_telegram_message(self, user_id: str, message: str, parse_mode: str = "HTML", **kwargs):
        """Send message via Telegram with error handling"""
        if not self.bot:
            logger.info(f"Mock send to {user_id}: {message}")
            return True
            
        try:
            await self.bot.send_message(
                chat_id=user_id, 
                text=message, 
                parse_mode=parse_mode,
                **kwargs
            )
            return True
            
        except Forbidden:
            logger.warning(f"User {user_id} blocked the bot")
            return False
        except BadRequest as e:
            logger.error(f"Bad request for user {user_id}: {e}")
            return False
        except NetworkError as e:
            logger.error(f"Network error sending to {user_id}: {e}")
            return False
        except TelegramError as e:
            logger.error(f"Telegram error sending to {user_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending message: {e}")
            return False
    
    async def send_wallet_alert(self, user_id: str, transaction: Dict):
        """Send alert to user about followed wallet"""
        try:
            formatted_tx = self.format_transaction(transaction)
            message = f"🚨 WHALE ALERT 🐋\n\nFollowed wallet activity!\n\n{formatted_tx}"
            
            success = await self.send_telegram_message(
                user_id=user_id,
                message=message,
                disable_web_page_preview=True
            )
            
            # Log notification
            self.log_notification(user_id, 'wallet_alert', message, success)
            
            if success:
                logger.info(f"Sent wallet alert to user {user_id}")
            
        except Exception as e:
            logger.error(f"Unexpected error sending wallet alert: {e}")
            self.log_notification(user_id, 'wallet_alert', str(e), False)
    
    async def send_price_alert(self, user_id: str, price_data: Dict):
        """Send price alert to user"""
        try:
            message = self.format_price_alert(price_data)
            
            success = await self.send_telegram_message(user_id=user_id, message=message)
            self.log_notification(user_id, 'price_alert', message, success)
            
            if success:
                logger.info(f"Sent price alert to user {user_id}")
                
        except Exception as e:
            logger.error(f"Error sending price alert: {e}")
            self.log_notification(user_id, 'price_alert', str(e), False)
    
    async def send_news_alert(self, user_id: str, news_item: Dict):
        """Send news alert to user"""
        try:
            title = news_item.get('title', 'TON News Update')
            summary = news_item.get('summary', '')
            url = news_item.get('url', '')
            source = news_item.get('source', 'Unknown')
            
            # Truncate summary for display
            display_summary = summary[:200] + '...' if len(summary) > 200 else summary
            
            message = f"""
<b>📰 TON NEWS ALERT</b>

<b>{title}</b>

{display_summary}

<b>Source:</b> {source}
{f'<a href="{url}">📖 Read More</a>' if url else ''}
            """.strip()
            
            success = await self.send_telegram_message(
                user_id=user_id,
                message=message,
                disable_web_page_preview=True
            )
            
            self.log_notification(user_id, 'news_alert', message, success)
            
            if success:
                logger.info(f"Sent news alert to user {user_id}")
                
        except Exception as e:
            logger.error(f"Error sending news alert: {e}")
            self.log_notification(user_id, 'news_alert', str(e), False)
    
    async def send_custom_alert(self, user_id: str, alert_type: str, data: Dict):
        """Send custom alert to user"""
        try:
            message = data.get('message', 'Custom alert')
            parse_mode = data.get('parse_mode', 'HTML')
            
            success = await self.send_telegram_message(
                user_id=user_id,
                message=message,
                parse_mode=parse_mode
            )
            
            self.log_notification(user_id, alert_type, message, success)
            
            if success:
                logger.info(f"Sent {alert_type} alert to user {user_id}")
                
        except Exception as e:
            logger.error(f"Error sending custom alert: {e}")
            self.log_notification(user_id, alert_type, str(e), False)
    
    def log_notification(self, user_id: str, notification_type: str, message: str, success: bool):
        """Log notification to database"""
        try:
            conn = sqlite3.connect('notifications.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO notification_history (user_id, notification_type, message, success)
                VALUES (?, ?, ?, ?)
            ''', (user_id, notification_type, message, success))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Failed to log notification: {e}")
    
    def add_followed_wallet(self, user_id: str, wallet_address: str, wallet_name: str = None, min_amount: float = 0):
        """Add wallet to user's follow list"""
        try:
            conn = sqlite3.connect('notifications.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO followed_wallets (user_id, wallet_address, wallet_name, min_amount)
                VALUES (?, ?, ?, ?)
            ''', (user_id, wallet_address, wallet_name or 'Unknown Wallet', min_amount))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Added wallet {wallet_address} to user {user_id}'s follow list")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add followed wallet: {e}")
            return False
    
    def remove_followed_wallet(self, user_id: str, wallet_address: str):
        """Remove wallet from user's follow list"""
        try:
            conn = sqlite3.connect('notifications.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM followed_wallets 
                WHERE user_id = ? AND wallet_address = ?
            ''', (user_id, wallet_address))
            
            conn.commit()
            rows_affected = cursor.rowcount
            conn.close()
            
            if rows_affected > 0:
                logger.info(f"Removed wallet {wallet_address} from user {user_id}'s follow list")
                return True
            else:
                logger.warning(f"Wallet {wallet_address} not found for user {user_id}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to remove followed wallet: {e}")
            return False
    
    def get_followed_wallets(self, user_id: str) -> List[Dict]:
        """Get list of wallets followed by user"""
        try:
            conn = sqlite3.connect('notifications.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT wallet_address, wallet_name, min_amount, created_at 
                FROM followed_wallets 
                WHERE user_id = ?
                ORDER BY created_at DESC
            ''', (user_id,))
            
            results = cursor.fetchall()
            conn.close()
            
            wallets = []
            for row in results:
                wallets.append({
                    'address': row[0],
                    'name': row[1],
                    'min_amount': row[2],
                    'created_at': row[3]
                })
            
            return wallets
            
        except Exception as e:
            logger.error(f"Failed to get followed wallets: {e}")
            return []
    
    def enable_notifications(self, user_id: str, notification_type: str, settings: Dict = None):
        """Enable notifications for user"""
        try:
            conn = sqlite3.connect('notifications.db')
            cursor = conn.cursor()
            
            settings_json = json.dumps(settings) if settings else None
            
            cursor.execute('''
                INSERT OR REPLACE INTO user_notifications (user_id, notification_type, enabled, settings)
                VALUES (?, ?, 1, ?)
            ''', (user_id, notification_type, settings_json))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Enabled {notification_type} notifications for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to enable notifications: {e}")
            return False
    
    def disable_notifications(self, user_id: str, notification_type: str):
        """Disable notifications for user"""
        try:
            conn = sqlite3.connect('notifications.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE user_notifications 
                SET enabled = 0 
                WHERE user_id = ? AND notification_type = ?
            ''', (user_id, notification_type))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Disabled {notification_type} notifications for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to disable notifications: {e}")
            return False
    
    def is_notifications_enabled(self, user_id: str, notification_type: str) -> bool:
        """Check if notifications are enabled for user"""
        try:
            conn = sqlite3.connect('notifications.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT enabled FROM user_notifications 
                WHERE user_id = ? AND notification_type = ?
            ''', (user_id, notification_type))
            
            result = cursor.fetchone()
            conn.close()
            
            return bool(result and result[0]) if result else True  # Default to enabled
            
        except Exception as e:
            logger.error(f"Failed to check notification status: {e}")
            return False
    
    def get_notification_settings(self, user_id: str, notification_type: str) -> Optional[Dict]:
        """Get notification settings for user"""
        try:
            conn = sqlite3.connect('notifications.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT settings FROM user_notifications 
                WHERE user_id = ? AND notification_type = ?
            ''', (user_id, notification_type))
            
            result = cursor.fetchone()
            conn.close()
            
            if result and result[0]:
                return json.loads(result[0])
            return None
            
        except Exception as e:
            logger.error(f"Failed to get notification settings: {e}")
            return None
    
    async def broadcast_alert(self, message: str, notification_type: str = 'broadcast'):
        """Send alert to all users who have this notification type enabled"""
        try:
            conn = sqlite3.connect('notifications.db')
            cursor = conn.cursor()
            
            # Get all users with this notification type enabled
            cursor.execute('''
                SELECT DISTINCT user_id FROM user_notifications 
                WHERE notification_type = ? AND enabled = 1
            ''', (notification_type,))
            
            users = cursor.fetchall()
            conn.close()
            
            if not users:
                logger.info(f"No users found for broadcast type: {notification_type}")
                return 0
            
            success_count = 0
            for user_row in users:
                user_id = user_row[0]
                
                success = await self.send_telegram_message(user_id=user_id, message=message)
                self.log_notification(user_id, notification_type, message, success)
                
                if success:
                    success_count += 1
                
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.1)
            
            logger.info(f"Broadcast sent to {success_count}/{len(users)} users")
            return success_count
            
        except Exception as e:
            logger.error(f"Failed to send broadcast: {e}")
            return 0
    
    def get_notification_stats(self) -> Dict:
        """Get notification statistics"""
        try:
            conn = sqlite3.connect('notifications.db')
            cursor = conn.cursor()
            
            # Get total users
            cursor.execute('SELECT COUNT(DISTINCT user_id) FROM user_notifications')
            total_users = cursor.fetchone()[0]
            
            # Get notifications sent today
            cursor.execute('''
                SELECT COUNT(*) FROM notification_history 
                WHERE DATE(sent_at) = DATE('now')
            ''')
            today_notifications = cursor.fetchone()[0]
            
            # Get success rate
            cursor.execute('''
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful
                FROM notification_history 
                WHERE DATE(sent_at) >= DATE('now', '-7 days')
            ''')
            week_stats = cursor.fetchone()
            
            success_rate = (week_stats[1] / week_stats[0] * 100) if week_stats[0] > 0 else 0
            
            # Get notification types
            cursor.execute('''
                SELECT notification_type, COUNT(*) 
                FROM user_notifications 
                WHERE enabled = 1 
                GROUP BY notification_type
            ''')
            enabled_types = dict(cursor.fetchall())
            
            conn.close()
            
            return {
                'total_users': total_users,
                'notifications_today': today_notifications,
                'success_rate_7d': round(success_rate, 2),
                'enabled_notification_types': enabled_types
            }
            
        except Exception as e:
            logger.error(f"Failed to get notification stats: {e}")
            return {}

# Global notification service instance
notification_service = NotificationService()

# Export the main functions for backward compatibility
async def send_wallet_alert(user_id: str, transaction: Dict):
    """Send alert to user about followed wallet"""
    await notification_service.send_wallet_alert(user_id, transaction)

def format_transaction(transaction: Dict) -> str:
    """Format transaction data for display"""
    return notification_service.format_transaction(transaction)

# Health check function
def check_service_health() -> Dict:
    """Check if the notification service is healthy"""
    try:
        stats = notification_service.get_notification_stats()
        return {
            'status': 'healthy',
            'telegram_available': TELEGRAM_AVAILABLE,
            'bot_configured': notification_service.bot is not None,
            'stats': stats
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }

# Usage example and testing
async def main():
    """Example usage and testing"""
    logger.info("Testing notification service...")
    
    # Check service health
    health = check_service_health()
    logger.info(f"Service health: {health}")
    
    # Example transaction data
    sample_transaction = {
        'hash': '1234567890abcdef1234567890abcdef12345678',
        'from_address': 'EQD1Lp1KcmGHFpE8eIvL1mnHT83b4HdgHxShh5qEjLhV_Ded',
        'to_address': 'EQC5s0j2vL7pLwKy1jCJJ2QFmSH9J7Q_YmJ5kP2J6N7vL8Qr',
        'amount': 1000.5,
        'token': 'TON',
        'timestamp': datetime.utcnow(),
        'type': 'transfer'
    }
    
    # Test formatting
    formatted = format_transaction(sample_transaction)
    logger.info(f"Formatted transaction: {formatted}")
    
    # Test wallet management
    test_user_id = "123456789"
    notification_service.add_followed_wallet(
        test_user_id, 
        "EQD1Lp1KcmGHFpE8eIvL1mnHT83b4HdgHxShh5qEjLhV_Ded",
        "Test Whale Wallet",
        100.0
    )
    
    wallets = notification_service.get_followed_wallets(test_user_id)
    logger.info(f"Followed wallets: {wallets}")
    
    # Send test alert (replace with actual user ID for real testing)
    # await send_wallet_alert(test_user_id, sample_transaction)

if __name__ == "__main__":
    asyncio.run(main())