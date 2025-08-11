import os
import requests

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

ALLOWED_MODELS = {
    "gpt-3.5-turbo",
    "gpt-4",
    "mistral-7b-instruct",
    "openchat",
    "nous-hermes",
    "llama3",
}

DEFAULT_MODEL = "gpt-3.5-turbo"

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

def ask_gpt(prompt: str, model: str = DEFAULT_MODEL, context: str = "") -> str:
    if model not in ALLOWED_MODELS:
        raise ValueError(f"Model {model} is not supported.")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    messages = [
        {"role": "system", "content": context or "You are TonGPT, an expert in the TON ecosystem."},
        {"role": "user", "content": prompt}
    ]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 1000
    }

    try:
        response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print("Error in ask_gpt:", e)
        return "⚠️ GPT error. Please try again later."
