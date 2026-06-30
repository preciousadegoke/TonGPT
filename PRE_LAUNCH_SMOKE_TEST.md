# TonGPT — Pre-Launch Smoke Test

A short, runnable checklist to convert the audit's *inferred* confidence into a
*verified* one. Do these in order; stop and fix on the first red. Tick each box.

---

## 0. Build & static checks (must pass before anything else)

- [ ] **Python compiles:** `python -m compileall -q services handlers core api bot utils main.py` → no output.
- [ ] **C# builds:** `dotnet build backend/TonGPT.Engine` → `Build succeeded`, 0 errors.
- [ ] **Git is clean:** `git status` shows the deleted `services/payment_verifier.py` staged (run `git add -A`).
- [ ] No stray secrets committed: `git grep -nE "sk-[A-Za-z0-9]{20}|ENGINE_API_KEY=" -- ':!*.md'` returns nothing real.

## 1. Required environment / secrets (fail-closed if missing)

Set in **both** the bot env and the Engine config where noted.

- [ ] `BOT_TOKEN` (bot) — bot refuses to start without it.
- [ ] `ENGINE_API_KEY` (bot + Engine) — must match.
- [ ] `WALLET_LINK_SIGNING_SECRET` (bot + Engine, **same value**) — gates wallet linking *and* GDPR export/delete.
- [ ] `TONPROOF_ALLOWED_DOMAINS` — your Mini-App origin(s), comma-separated.
- [ ] `OPENAI_MODERATION_API_KEY` — a real `sk-...` key (an OpenRouter `sk-or-` key will **not** work; moderation now fails *closed*).
- [ ] `PAYMENT_WALLET_ADDRESS` (a.k.a. the TON monitored wallet — now unified) and `ENGINE_URL`, `ConnectionStrings__DefaultConnection`.
- [ ] TLS terminates at the edge for the Engine (HTTPS). Confirm no plain-HTTP path carries the API key.
- [ ] Optional but recommended: `MODERATION_REQUIRED=true` (refuse to start unmoderated), `INITDATA_MAX_AGE_SECONDS` (default 3600).

> **Startup self-check:** on boot, logs should show `moderation_ready` (not `moderation_enabled_but_no_usable_key`) and no `EngineApiKey not configured` warning.

## 2. Payments — Telegram Stars

- [ ] `/pay` shows tiers with the **canonical** prices (Starter **1335⭐**, Pro 4000⭐, Pro+ 8000⭐, Elite 16000⭐).
- [ ] `/upgrade` shows the **same** prices (no 75⭐ mismatch).
- [ ] Tap Starter → the Telegram invoice reads **⭐ 1335**, *not* 133,500 (ENG-002).
- [ ] Complete payment with test Stars → subscription activates; success message shown.
- [ ] **Duplicate:** replay the same charge → `AlreadyProcessed`, no second period.
- [ ] **Mini-App parity:** `/subscription/stars-invoice` opens an invoice with the same Star count.

## 3. Payments — TON (if `TON_PAYMENTS_ENABLED=true`)

- [ ] Send the exact TON amount with the memo → activates within a poll cycle.
- [ ] **Underpay** (send less) → no activation **and** you receive the "underpaid" notice (PAY-010).
- [ ] **Free-Elite attempt:** `POST /api/Payment/complete` with the API key, `Plan=Elite`, `AmountTon=0` → **400** (PAY-001).
- [ ] **Two transfers in one event** (if you can craft it) → both payers activate (PAY-004).
- [ ] **Engine-down queue:** stop the Engine, pay (Stars + TON), restart → both reconcile and activate (queue carries the amount).

## 4. Wallet linking (TON Connect)

- [ ] Connect a real wallet (Tonkeeper / Tonhub) → `wallet.authed === true`; a `wallet_linked` row appears; stored address is canonical friendly (`EQ…`/`UQ…`).
- [ ] **Spoof:** replay `/wallet/auth` with a `public_key` you control + victim address, re-signed → **403** (AUTH-001).
- [ ] **Magic-string bypass:** `POST /api/Wallet/auth` with API key + `Proof="VERIFIED_BY_PYTHON_SERVER"` → **403** (ENG-001).
- [ ] **Expired assertion:** capture a valid `ua…`/`v1…` token, wait 60s, replay to the Engine → **403**.

## 5. AI / moderation / rate limiting

- [ ] `/ask` returns a normal answer.
- [ ] **Input moderation:** a clearly disallowed prompt is refused (with a category-appropriate message).
- [ ] **Output moderation (MOD-002):** confirm a response that trips a category is replaced with the refusal text.
- [ ] **Rate limit (RLIM-001):** as a free user, fire ~20 `/ask` in parallel (cap 3/min) → exactly 3 allowed, rest limited; no overflow.
- [ ] **Limiter fail-closed (RL-001):** stop Redis, hammer a `/api/` route → 429 after ~30/min/IP, **not** unlimited.

## 6. Mini-App

- [ ] Mini-App loads; `initData` HMAC accepted; a tampered/old (>1h) `initData` → **401** (MINI-001).
- [ ] Pricing screen matches `core/pricing.py`.
- [ ] Wallet connect + a Stars invoice both work from inside the Mini-App.

## 7. Error / reliability paths

- [ ] **Supervised tasks (MAIN-001):** kill/raise in one background loop → logged crash + auto-restart; bot stays up.
- [ ] **Idempotent init (INIT-001):** force an init retry → "Background tasks already started — skipping" appears once; monitors not duplicated.
- [ ] **Engine timeout (PAY-011):** point `ENGINE_URL` at a black-hole port → calls fail within ~10s into the queue, monitor doesn't hang.
- [ ] **Auth lockout (ARCH-002):** send 10+ bad API keys from one IP → subsequent requests get **429** for the lockout window.
- [ ] **GDPR:** `/export` returns only the requesting user's data; `/deletedata` anonymizes; both reject without a valid per-user assertion.

## 8. GDPR / data

- [ ] `ChatRetentionJob` prunes old chat + `ActivityLogs` (check logs after the interval, or lower `RetentionDays` to test).

---

### Sign-off
- [ ] All boxes above green.
- [ ] Register shows 0 CRITICAL / 0 HIGH open.
- [ ] On-call + rollback plan in place.

_If every box is ticked, the project is launch-ready at the verified (not inferred) confidence level._
