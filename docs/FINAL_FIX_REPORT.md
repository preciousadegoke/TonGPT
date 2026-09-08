# TonGPT — Final Pre-Launch Fix Report

Follow-up to `LAUNCH_FIX_REPORT.md`. Covers: moderation Option B, the persisting toncenter 422, and the independent audit.

---

## 1. Moderation fix (Option B — implemented)

**Blast radius (traced):** `moderate_text` gates exactly two call sites, both in `handlers/gpt_reply.py` — the input gate before every GPT call and the output screen after it. That covers `/ask`, every private text message, and the general-message handler — i.e. **the entire AI chat product**. Nothing else is gated: commands (/check, /watchlist, /scan…) and the Mini-App have no moderation dependency. So "BLOCKED with no key" was killing the core product, exactly as feared.

**The fix — `MODERATION_MODE` (default `auto`)** in `services/moderation_service.py`:

| Mode | Behavior |
|---|---|
| `auto` (default) | OpenAI `/v1/moderations` if a real `sk-` key exists → else **LLM classifier via OpenRouter** (strict SAFE/UNSAFE prompt, temp 0, your existing `sk-or-` key) → else local pre-filter |
| `openai` | OpenAI only; fail-closed if key missing (explicit choice) |
| `model` | OpenRouter classifier only |
| `local` | Built-in high-risk regex pre-filter only |
| `off` | Explicit opt-out, logged loudly |

Key properties: a **local zero-dependency pre-filter runs first in every mode** (high-precision patterns for the worst categories only: sexual/minors, self-harm intent, explicit threats, weapon-synthesis instructions — precision over recall so "how to kill a process" never blocks). "Key absent" now selects a fallback and **never** blocks all chat; fail-closed applies only to genuine errors inside the *active* path (HTTP errors, timeouts, malformed classifier output). Startup logs the active mode explicitly (`moderation_mode_active mode=model …`). `MODERATION_REQUIRED=true` still refuses to start if only the local tripwire is available.

**Acceptance (run after rebuild):** with no OpenAI key: (1) boot log shows `moderation_mode_active mode=model`; (2) "what's the price of TON?" gets a GPT reply; (3) an abusive test message gets the block message, not a reply; (4) with an OpenAI `sk-` key added, log shows `mode=openai`.

**Files:** `services/moderation_service.py`, `.env`, `.env.example` (new `MODERATION_MODE`, `MODERATION_FALLBACK_MODEL`).

## 2. toncenter 422 — root cause and launch posture

**What the 422 body says: your running engine never printed one — and that's the diagnosis.** The current source (previous pass) logs `toncenter runGetMethod returned {status} … Body: {body}` on every non-200, AND is gated behind `Subscription:EnablePolling`, which is set nowhere in your config — so current source would log one "SubscriptionWorker disabled" line and never poll. Your log shows polling continuing with no body logged: **the container is still running the pre-fix image.** The `docker compose build --no-cache tongpt-engine` from the last report hasn't taken effect.

**Schema verification (done independently):** current toncenter v2 expects `stack` slice args as `["tvm.Slice", "<base64 BOC>"]` — a base64-serialized bag-of-cells, not a raw address string ([toncenter v2](https://toncenter.com/api/v2/), [Chainstack runGetMethod reference](https://docs.chainstack.com/reference/ton-rungetmethod-v2), [TON docs tonlib types](https://docs.ton.org/applications/api/toncenter/v2-tonlib-types)). The rewritten worker already sends exactly that (minimal BOC serializer), calls the contract's real getter `subscriptionInfo`, and sends `X-API-Key` (now also wired in compose via `TonCenter__ApiKey=${TONCENTER_API}`). Testnet without a key is heavily throttled — the key matters.

**Launch posture (Step 4 recommendation): ship with on-chain verification OFF — which is already the default.** Reasons: (a) the contract at `0QBe…` is an unaudited testnet artifact — the register (TOLK-001…003) documents a bounce-handling bug and tier encoding that doesn't match canonical pricing; (b) the canonical activation path is off-chain (`Payment/complete` → DB `SubscriptionExpiry`), idempotent, amount-validated, and harness-verified; (c) a broken get-method must never gate paying users. Turn `Subscription:EnablePolling=true` on post-launch only after the contract is deployed + audited.

**Acceptance:** after the `--no-cache` rebuild: zero `Checking subscriptions...` lines, zero 422s; one Stars sandbox purchase → `/subscription` shows plan + expiry from the DB path.

## 3. Independent audit findings

| # | Finding | Severity | Why it matters for launch | Smallest fix | Status |
|---|---------|----------|---------------------------|--------------|--------|
| A1 | **Live secrets in the repo tree**: `.env` holds the real bot token, OpenRouter key, TONAPI + toncenter keys; `docker-compose.yml` (a committed file) hardcoded `EngineApiKey`; dev Postgres password is `password` in two committed files | **P0** | Any repo share/leak = full account takeover: your bot, your OpenRouter balance, your engine. The compose file is the worst offender because it's definitely committed | Compose now interpolates `EngineApiKey=${ENGINE_API_KEY}` from `.env` (done). **You must rotate**: BOT_TOKEN (@BotFather), OpenRouter key, TONAPI key, toncenter key, ENGINE_API_KEY (any random 64-hex). `.gitignore` does cover `.env` — but check `git log --all -- .env` to see if it was ever committed; if yes, rotate is mandatory, not optional | ⚠️ rotation = yours |
| A2 | **Moderation blocked all chat** (Part 1) | P0 | Dead product | `MODERATION_MODE=auto` fallback chain | ✅ fixed |
| A3 | **No EF migrations on boot** — fresh Postgres (first Fly.io deploy, wiped volume) has no schema; every query 500s | **P1** | First real deploy fails in a confusing way at the worst moment | `Database.Migrate()` on startup when pending migrations exist (`Database:MigrateOnStartup`, default true) | ✅ fixed |
| A4 | **Bot persisted chat history without consent** — the Mini-App collects `ConsentVersion=v1`, but the bot's "Chat with AI" path saved every conversation to Postgres unconditionally → privacy-claim mismatch | **P1** | "We ask for consent" + "we store regardless" is a day-one embarrassment and a GDPR problem; you already built /export and /deletedata — don't undermine them | Durable save now gated on `_has_consent()` (Engine consent field, 1h Redis cache, fail = don't persist). Ephemeral Redis context still gives continuity | ✅ fixed |
| A5 | **Deploy is `Development` posture**: compose sets `ASPNETCORE_ENVIRONMENT=Development` → Swagger UI served **auth-exempt** on published port 5090, HSTS/HTTPS-redirect off, verbose errors | **P1** | Fine on your laptop; on any internet-reachable host this exposes the whole engine API surface unauthenticated via Swagger | For Fly.io: `ASPNETCORE_ENVIRONMENT=Production`, secrets via `fly secrets set`, Postgres as managed/attached volume, engine NOT publicly exposed (internal networking only; only the bot + miniapp need it), health checks on `/health` if present else TCP | 📋 deploy checklist |
| A6 | **Payment path e2e today**: Stars is the only live rail — verified wired end-to-end (XTR invoice `provider_token=""`, amount validated vs `expected_stars`, `Payment/complete` idempotent, durable queue + dead-letter behind it). TON button correctly shows "Coming Soon → use Stars" when disabled | ✅ OK | A paying user CAN activate today via Stars; no gap found. TON manual path correctly gated | Final gate: one live sandbox Stars charge (register's standing item) | verify live |
| A7 | Error handling on user-facing paths: GPT down → friendly retry message (no stack traces found on chat path); TON API down → cached/stale + "unavailable" states; Redis down → in-proc fallbacks (rate limiter fail-safe, guardian cooldown degrades). One gap: several `except Exception` handlers reply generic ❌ without error IDs, making user reports hard to correlate | P2 | Debuggability, not availability | Post-launch: add a short error-id to generic error replies | 📋 later |
| A8 | New `/check`/guardian path has no per-user rate limit (DexScreener is cached 45s + breaker-protected, so cost is bounded) | P2 | Worst case: one user spins the cache; upstream is free | Reuse `create_rate_limit_decorator` on `/check` if abused | 📋 later |

## 4. Apply in order

**Terminal commands:**
```bash
# 1. Rotate secrets (A1) — BotFather /revoke, OpenRouter + tonconsole dashboards,
#    then write the NEW values into .env (never commit it):
#    BOT_TOKEN, OPENROUTER_API_KEY/OPENAI_API_KEY, TONAPI_KEY/TON_API_KEY,
#    TONCENTER_API, ENGINE_API_KEY (new random: openssl rand -hex 32)

# 2. Check whether .env was ever committed (decides how urgent A1 is):
git log --all --oneline -- .env

# 3. THE rebuild (root cause of the persisting 422 — this time verify it):
docker compose down
docker compose build --no-cache tongpt-engine tongpt-bot
docker compose up -d
docker compose logs -f | grep -iE "subscriptionworker|moderation_mode|422"
# expect: "SubscriptionWorker disabled", "moderation_mode_active mode=model", no 422s

# 4. Acceptance for Part 1 (no OpenAI key):
#    - send a normal message -> GPT reply
#    - send an abusive test message -> block message
```

**File edits (already applied):** `services/moderation_service.py`, `.env`, `.env.example`, `bot/commands.py` (consent gate), `backend/TonGPT.Engine/Program.cs` (migrate-on-boot), `docker-compose.yml` (key interpolation + toncenter API key).

**Fly.io deploy checklist (A5, when you go):** `ASPNETCORE_ENVIRONMENT=Production`; all secrets via `fly secrets set` (nothing in fly.toml); engine on internal networking only (`.internal`), never a public IP; managed Postgres or volume-backed with backups; Redis with persistence (or accept cache loss); `FAIL_ON_INIT_ERROR=true` for the bot; `MODERATION_REQUIRED=true` once you have any key; min 512MB for the engine, 256–512MB for the bot.
