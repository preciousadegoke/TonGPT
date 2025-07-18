import os
import requests
from dotenv import load_dotenv

load_dotenv()

def ask_gpt(prompt, context=""):
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return "❌ Missing OpenRouter API key."

    try:
        full_prompt = context + "\n\n" + prompt if context else prompt

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": "openai/gpt-3.5-turbo",  # or try "mistralai/mixtral-8x7b", "meta-llama/llama-3-70b-instruct"
            "messages": [
                {"role": "system", "content": (
                    "You are TON AlphaBot, a Telegram-based assistant for TON memecoins, STON.fi, whales, and alpha. "
                    "Be concise, crypto-native, and sharp in your responses. Use emojis when fitting. "
                    "When unsure, reply with 'Still digging 🕵️—come back in a few blocks.'"
                )},
                {"role": "user", "content": full_prompt}
            ]
        }

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=15
        )

        if response.status_code != 200:
            print("OpenRouter error:", response.status_code, response.text)
            return "❌ GPT request failed (OpenRouter)"

        reply = response.json()["choices"][0]["message"]["content"]
        return reply.strip()

    except Exception as e:
        print("GPT Error:", e)
        return "❌ GPT request failed. Try again later."
