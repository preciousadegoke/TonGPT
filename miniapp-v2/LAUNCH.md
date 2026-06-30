# TonGPT Mini-App v2 — Launch Guide & Final Checklist

Everything needed to take `miniapp-v2/` live and retire the legacy `miniapp/`.

---

## 1. One required backend addition: Stars invoice

The Mini-App's Stars rail needs a backend endpoint to mint invoice links (the
browser can't hold a bot token). The drop-in is ready:

- Code: [`server-additions/stars_invoice.py`](./server-additions/stars_invoice.py)
- Paste the `POST /api/subscription/stars-invoice` route into
  `api/miniapp_server.py` (it reuses the existing `verify_telegram_init_data`).
- It reuses your canonical `core.pricing.PLANS`, the live bot via
  `core.bot_instance.get_bot()`, and the payload format `premium_{plan_key}` —
  so your **existing** `pre_checkout_query` + `successful_payment` handlers in
  `handlers/pay.py` finish activation with **no changes**.
- ⚠️ For Stars (`XTR`), `provider_token` **must be empty** in
  `create_invoice_link` (already done in the snippet).

Optional (recommended) in the same file: `GET /api/wallet/balance` proxy for the
Wallet screen. If you skip it, the app falls back to public toncenter.

Optional: `GET /api/stats` returning `{ members, signals_24h, upgrades_7d }`
powers the Pricing social-proof strip. If absent, the app shows an honest
generic trust line with **no fabricated numbers**.

---

## 2. Pricing parity (verify before launch)

The frontend now matches `core/pricing.py` exactly:

| Plan | TON | Stars |
| --- | --- | --- |
| Starter | 10 | 1,335 ⭐ |
| Pro (most popular) | 30 | 4,000 ⭐ |
| Pro+ | 60 | 8,000 ⭐ |
| Elite | 120 | 16,000 ⭐ |

If you ever change `core/pricing.py`, update `src/config/index.ts → PLANS` to
match. (The previous frontend was charging half the TON price — now fixed.)

---

## 3. Config & secrets

```bash
cd miniapp-v2
cp .env.example .env.local
```

Set:
- `VITE_TONCONNECT_MANIFEST_URL` → public HTTPS URL of `tonconnect-manifest.json`
- `VITE_TON_NETWORK` → `mainnet`
- `VITE_BOT_USERNAME` → your bot (no `@`)
- `VITE_API_BASE_URL` → leave blank if the backend serves the app (same-origin `/api`)

Edit `tonconnect-manifest.json` → real `url`, `iconUrl`, `termsOfUseUrl`,
`privacyPolicyUrl` (wallets fetch this; it must be reachable publicly).

---

## 4. Build & serve

```bash
npm install
npm run build          # tsc typecheck + vite build → dist/
npm run analyze        # optional: inspect bundle; tonconnect is its own chunk
```

Serve `dist/` from FastAPI (StaticFiles) or any static host behind HTTPS, then
set the Mini-App URL in **@BotFather → Bot Settings → Menu Button / Web App**.

---

## 5. Final pre-switch checklist

**Backend**
- [ ] `POST /api/subscription/stars-invoice` added and returns a link in-client
- [ ] Stars test purchase activates the plan (existing `successful_payment` path)
- [ ] `/api/wallet/balance` added (or accept public-toncenter fallback)
- [ ] `/api/user/status` reflects the new plan immediately after payment

**Payments**
- [ ] TON checkout charges the **correct** amount (10/30/60/120) and verifies BOC
- [ ] Stars checkout opens native invoice and completes
- [ ] Cancel/reject returns to idle with no scary error; failure offers recovery
- [ ] Success state + success haptic + plan badge updates

**Telegram-native**
- [ ] Theme auto-syncs dark↔light live; no FOUC on open
- [ ] BackButton on Wallet; MainButton/haptics behave; safe-area respected
- [ ] Consent gate works on first open; skipped afterward

**Wallet**
- [ ] Connect → ton_proof verified → status shows "Ownership verified"
- [ ] Balance loads (or shows "Unavailable" gracefully)
- [ ] Tonscan link + copy + disconnect work

**Design & UX (v2.1 premium refresh — see [DESIGN.md](./DESIGN.md))**
- [ ] Pricing reads as the hero: gradient headline, "Most popular" card clearly dominant, cards reveal on scroll
- [ ] Tier card CTAs open checkout; segmented TON/Stars thumb springs between rails
- [ ] Checkout success shows pop+ping+crown; error always offers retry / switch-to-Stars
- [ ] Tab bar uses glass chrome + crisp icons; active state tinted; haptics on tab change
- [ ] Inter loads but app paints instantly on the system fallback (no layout shift)
- [ ] `prefers-reduced-motion` ON → reveals/counters/animations snap, nothing janks
- [ ] Dark **and** light Telegram themes both look correct (derived tokens re-theme)
- [ ] No emoji-as-icon regressions; numbers use tabular figures and align

**Quality**
- [ ] `npm run typecheck` clean
- [ ] `npm run build` succeeds; `tonconnect` stays its own chunk (`npm run analyze`)
- [ ] Lighthouse (mobile) performance ≥ 90 on `dist/`
- [ ] Error boundary catches render crashes with a Reload action
- [ ] Run the full [TESTING.md](./TESTING.md) checklist inside real Telegram

**Cutover**
- [ ] Point bot Mini-App URL at the new `dist/`
- [ ] Smoke test end-to-end with a real account
- [ ] Archive/remove legacy `miniapp/` once verified
