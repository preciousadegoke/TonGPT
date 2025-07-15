from utils.ton_api import get_token_price

def register_commands(bot):
    @bot.message_handler(commands=['start'])
    def start(message):
        bot.reply_to(message,
            "👋 Welcome to TonGPT!\n\n"
            "I’m your on-chain assistant for the TON ecosystem.\n\n"
            "Try /price <token> to get meme coin prices on TON!"
        )

    @bot.message_handler(commands=['price'])
    def price(message):
        try:
            parts = message.text.split()
            if len(parts) != 2:
                return bot.reply_to(message, "Usage: /price <symbol>\nExample: /price NOT")

            symbol = parts[1].upper()
            price = get_token_price(symbol)

            if price:
                bot.reply_to(message, f"💰 {symbol} is currently **${price:.4f}**")
            else:
                bot.reply_to(message, f"❌ Couldn't fetch price for {symbol}")
        except Exception as e:
            bot.reply_to(message, f"⚠️ Error: {e}")
