import telebot
from dotenv import load_dotenv
import os
from bot.commands import register_commands

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = telebot.TeleBot(BOT_TOKEN)

register_commands(bot)

print("🤖 TonGPT is running...")
bot.polling()
