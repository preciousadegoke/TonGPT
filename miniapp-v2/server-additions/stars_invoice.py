# ──────────────────────────────────────────────────────────────────────────
# Stars invoice endpoint for the Mini-App.  DROP-IN for api/miniapp_server.py
# ──────────────────────────────────────────────────────────────────────────
#
# The Mini-App can't talk to the Bot API directly (no bot token in the browser),
# so it asks the backend to mint a one-time Stars invoice link. The link is then
# opened client-side with Telegram.WebApp.openInvoice().
#
# This reuses your EXISTING pipeline:
#   • core.pricing.PLANS            → canonical prices (price_stars)
#   • core.bot_instance.get_bot()   → the live aiogram Bot
#   • payload "premium_{plan_key}"  → your existing pre_checkout_query +
#                                     successful_payment handlers in handlers/pay.py
#                                     already validate this payload and activate
#                                     the plan. No changes needed there.
#
# HOW TO INSTALL
#   Paste the route below into api/miniapp_server.py (it relies on the
#   verify_telegram_init_data() helper already defined there). Then the
#   front-end endpoint endpoints.starsInvoice ("/subscription/stars-invoice")
#   is live.
#
# IMPORTANT — Stars (XTR) require an EMPTY provider_token. Even though your
# send_invoice() path passes PAYMENT_TOKEN, create_invoice_link for XTR must use
# provider_token="".  (Telegram Bot API: digital goods paid in Stars take no
# provider token.)

from aiogram.types import LabeledPrice
from fastapi import Request, HTTPException
from core.pricing import PLANS
from core.bot_instance import get_bot


@miniapp.post("/api/subscription/stars-invoice")
async def create_stars_invoice(request: Request, body: dict):
    """Mint a Telegram Stars invoice link for the given plan."""
    # 1. Authenticate the Telegram user via initData HMAC (same as every route).
    try:
        tg_user = verify_telegram_init_data(
            request.headers.get("X-Telegram-Init-Data", "")
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Telegram init data")

    # 2. Resolve the plan from the canonical table.
    plan_key = (body or {}).get("plan", "")
    plan = PLANS.get(plan_key)
    if not plan:
        raise HTTPException(status_code=400, detail="Invalid plan")

    bot = get_bot()
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot not ready")

    # 3. Create the invoice link. amount is in the smallest unit (Stars * 100 is
    #    what your send_invoice path uses; keep it identical for consistency).
    try:
        invoice_url = await bot.create_invoice_link(
            title=f"TonGPT {plan['name']}",
            description=f"Upgrade to {plan['name']} (1 month).",
            payload=f"premium_{plan_key}",          # ← matches existing handlers
            provider_token="",                       # ← REQUIRED empty for XTR/Stars
            currency="XTR",
            prices=[LabeledPrice(label=plan["name"], amount=plan["price_stars"] * 100)],
        )
    except Exception as e:                           # noqa: BLE001
        logger.error(f"create_stars_invoice failed for {plan_key}: {e}")
        raise HTTPException(status_code=502, detail="Could not create invoice")

    return {"invoice_url": invoice_url}


# ──────────────────────────────────────────────────────────────────────────
# OPTIONAL: balance proxy used by the Wallet screen (keeps API keys server-side).
#   Front-end calls GET /api/wallet/balance?address=… and falls back to public
#   toncenter if this route is absent — so it's optional but recommended.
# ──────────────────────────────────────────────────────────────────────────
import httpx  # noqa: E402


@miniapp.get("/api/wallet/balance")
async def wallet_balance(address: str):
    """Return the TON balance (in TON, not nanotons) for an address."""
    base = "https://toncenter.com/api/v2/getAddressBalance"  # use testnet host if needed
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(base, params={"address": address})
            j = r.json()
        if not j.get("ok"):
            raise HTTPException(status_code=502, detail="Balance unavailable")
        return {"balance": int(j["result"]) / 1_000_000_000}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"wallet_balance failed: {e}")
        raise HTTPException(status_code=502, detail="Balance unavailable")
