from telebot.types import Message
from gpt.engine import ask_gpt
from utils.scanner import fetch_trending_tokens
from utils.tonviewer import get_token_info_from_tonviewer


def register_commands(bot):

    @bot.message_handler(commands=['start'])
    def start(message: Message):
        bot.reply_to(
            message,
            "👋 Welcome to TonGPT!\n\n"
            "I’m your on-chain assistant for the TON ecosystem.\n\n"
            "Try:\n"
            "/info <contract_address> – to explore TON tokens\n"
            "/ask <your question> – to get alpha insights\n"
            "/scan – to list trending meme tokens\n"
            "/trending – GPT alpha summary of today’s top tokens"
        )

    @bot.message_handler(commands=['info'])
    def info(message: Message):
        try:
            parts = message.text.split()
            if len(parts) != 2:
                return bot.reply_to(message, "Usage: /info <contract_address>")

            address = parts[1]
            data = get_token_info_from_tonviewer(address)

            if not data:
                return bot.reply_to(message, "❌ Couldn't fetch info. Check the address and try again.")

            reply = f"🔎 {data.get('title', 'Unknown Token')}\n"
            reply += f"📦 Supply: {data.get('supply', 'N/A')}\n"
            reply += f"👥 Holders: {data.get('holders', 'N/A')}\n"
            reply += f"{data.get('verified', '❓')} Verified"

            bot.reply_to(message, reply)

        except Exception as e:
            bot.reply_to(message, f"⚠️ Error: {e}")

    @bot.message_handler(commands=['ask'])
    def handle_ask(message: Message):
        question = message.text.replace("/ask", "").strip()

        if not question:
            return bot.reply_to(message, "🧠 Ask me something like:\n/ask What memecoins are trending today?")

        bot.send_chat_action(message.chat.id, "typing")
        
        # Optional: include trending context
        context = ""
        if "meme" in question.lower() or "ton" in question.lower():
            tokens = fetch_trending_tokens()
            context = "Top TON Memecoins:\n" + "\n".join(
                [f"{t['symbol']} – {t['change']}% | ${t['price']}" for t in tokens]
            )
        
        reply = ask_gpt(question, context)
        bot.reply_to(message, reply)

    @bot.message_handler(commands=['scan'])
    def handle_scan(message: Message):
        tokens = fetch_trending_tokens()

        if not tokens:
            return bot.reply_to(message, "❌ Couldn't fetch memecoin list right now.")

        reply = "🔥 *Top TON Memecoins Today:*\n\n"
        for token in tokens:
            reply += f"• ${token['symbol']} — {token['change']}% | ${token['price']}\n"

        bot.reply_to(message, reply, parse_mode="Markdown")

    @bot.message_handler(commands=['trending'])
    def handle_trending(message: Message):
        tokens = fetch_trending_tokens(limit=7)
        if not tokens:
            return bot.reply_to(message, "❌ Couldn't fetch trending token data.")

        context = "Top TON Meme Tokens by Volume:\n"
        context += "\n".join(
            [f"• ${t['symbol']} | {t['change']}% | ${t['price']}" for t in tokens]
        )

        prompt = (
            f"{context}\n\n"
            "Based on volume and price changes, what memecoins are most promising? "
            "Consider hype, volatility, and Twitter buzz. Return insights in a crypto-native tone, not financial advice."
        )

        bot.send_chat_action(message.chat.id, "typing")
        reply = ask_gpt(prompt)
        bot.reply_to(message, reply)
