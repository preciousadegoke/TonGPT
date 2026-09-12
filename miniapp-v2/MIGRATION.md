# Migration: Vanilla `miniapp/` → `miniapp-v2/`

The app now lives in `miniapp-v2/`. Docker/Nginx and FastAPI serve its compiled
`dist/` directory. The legacy source folder is retired; no rename is required.

## What maps to what

| Legacy file | Replaced by | Notes |
| --- | --- | --- |
| `index.html` (Tailwind CDN, script tags) | `index.html` + Vite bundle | No CDN; Tailwind compiled, code-split |
| `static/js/config.js` | `src/config/index.ts` | Typed; PLANS now include `priceStars` |
| `static/js/app.js` (`TonGPTApp` god-class) | `App.tsx` + screens + signals store | State is reactive, not a mutable object |
| `static/js/api.js` | `src/lib/api.ts` | Same initData header; typed errors |
| `static/js/tonconnect.js` | `src/lib/tonconnect.ts` | **Adds ton_proof** (was missing) |
| `static/js/views.js` (innerHTML strings) | `src/screens/*` (Preact components) | No XSS surface from string HTML |
| `static/js/utils.js` | `src/lib/format.ts` | Trimmed to what's used |
| `hero.js` / `hero.css` (Three.js) | _dropped_ | Heavy 3D hero hurt load time; replace with the lightweight Home dashboard. Re-add later behind `lazy()` if desired |

## Bugs fixed during migration

1. **TonConnect was non-functional** — `config.js` `MANIFEST_URL` was the
   placeholder `https://your-domain.com/manifest.json`, and `buttonRootId:
   'ton-connect'` referenced a DOM node that didn't exist. v2 uses
   `env.manifestUrl` (from `.env`) and the modal API — no missing-node coupling.
2. **No ton_proof** — the wallet "connected" but never proved ownership. v2 arms
   a server nonce (`/wallet/generate-payload`) and verifies the signed proof via
   `/wallet/auth` (both already exist in your FastAPI backend).
3. **Stars unavailable in the app** — Stars existed only in the bot. v2 adds a
   Stars rail via `Telegram.WebApp.openInvoice` (needs one new backend endpoint —
   below).
4. **Plan tiers inconsistent** between frontend (TON) and bot (Stars). Now one
   source of truth in `config/index.ts`.

## Backend changes required

### 1. New endpoint: Stars invoice link (only new work needed)

The Mini-App can't call the Bot API directly (no bot token client-side). Add a
thin endpoint that mints an invoice link with `createInvoiceLink`:

```python
# api/miniapp_server.py
from aiogram.types import LabeledPrice
from handlers.pay import SUBSCRIPTION_PLANS  # reuse the bot's plan table

@miniapp.post("/api/subscription/stars-invoice")
async def create_stars_invoice(request: Request, body: dict):
    tg_user = verify_telegram_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    plan_key = body.get("plan")                      # "starter" | "pro" | "pro_plus" | "elite"
    plan = SUBSCRIPTION_PLANS.get(plan_key)
    if not plan:
        raise HTTPException(400, "Invalid plan")

    from main import bot   # your aiogram Bot instance
    link = await bot.create_invoice_link(
        title=f"TonGPT {plan['name']}",
        description=f"{plan['name']} subscription (1 month)",
        payload=f"stars_{plan_key}_{tg_user['id']}",
        currency="XTR",
        prices=[LabeledPrice(label=plan['name'], amount=plan['price_stars'] * 100)],
    )
    return {"invoice_url": link}
```

Your existing `pre_checkout_query` + `successful_payment` handlers in
`handlers/pay.py` already finish the flow and activate the plan — no change
needed there. The Mini-App's `openInvoice` callback just reflects the result and
re-fetches `/api/user/status`.

### 2. (Optional) `/api/user/activity`

The Activity screen calls `/api/user/activity` for the payments tab. It degrades
gracefully to empty if missing — add it when convenient (return `[{plan, amount,
method, date}]`).

### 3. Serve the built app & manifest

Point FastAPI's static serving at `miniapp-v2/dist/` and host
`tonconnect-manifest.json` at a **public HTTPS** path (wallets fetch it). Update
the manifest `url`/`iconUrl` to your real domain before launch.

## Cutover checklist

- [ ] Add the Stars invoice endpoint
- [ ] Set real domain in `tonconnect-manifest.json` + `.env` `VITE_TONCONNECT_MANIFEST_URL`
- [ ] Confirm TON prices in `config/index.ts`
- [ ] `npm run build`, serve `dist/`, set Mini-App URL in @BotFather
- [ ] Run the test checklist (TESTING.md)
- [ ] Verify the root page and `/miniapp/` serve the built app and its assets
