from telebot.types import LabeledPrice, Message, PreCheckoutQuery
from utils.redis_conn import redis_client
import os

PAYMENT_TOKEN = os.getenv("PAYMENT_TOKEN")

def register_pay_handlers(bot):
    @bot.message_handler(commands=["pay", "subscribe"])
    def send_invoice(message: Message):
        prices = [LabeledPrice("TonGPT Premium (1 month)", 100 * 100)]  # 100 stars
        bot.send_invoice(
            chat_id=message.chat.id,
            title="TonGPT Premium",
            description="Real-time influencer alerts, portfolio tools, whale tracking, and more.",
            invoice_payload="premium_1month",
            provider_token=PAYMENT_TOKEN,
            currency="XTR",  # Telegram Stars currency code
            prices=prices,
            start_parameter="TonGPT",
            need_email=False
        )

    @bot.pre_checkout_query_handler(func=lambda q: True)
    def pre_checkout(pre_checkout_query: PreCheckoutQuery):
        if pre_checkout_query.invoice_payload == "premium_1month":
            bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

    @bot.message_handler(content_types=["successful_payment"])
    def handle_successful_payment(message: Message):
        user_id = message.from_user.id
        if message.successful_payment.invoice_payload == "premium_1month":
            redis_client.set(f"premium:{user_id}", "active", ex=30 * 24 * 3600)  # 30 days
            redis_client.incrbyfloat("revenue", 5.0)
            bot.send_message(message.chat.id, "✅ Premium activated for 1 month!\nTry /influencer or /wallet.")
