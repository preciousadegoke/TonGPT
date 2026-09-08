# TonGPT — Launch-Blocking Fix Report (boot log 2026-07-03)

Scope: the 5 runtime failures from the `docker compose up` boot log + full X/Twitter removal. All fixes applied minimally; no new features, no refactors beyond each fix.

---

## Summary table

| # | Issue | Root cause | Change | File(s) touched | Acceptance test |
|---|-------|-----------|--------|-----------------|-----------------|
| 1 | toncenter `runGetMethod` 422 on every call, 6–12s each, Kestrel thread-pool starvation | **Three stacked causes:** (a) the running container was built from **stale pre-gate source** — current source gates the worker behind `Subscription:EnablePolling`, which is set nowhere, yet the log shows it polling; (b) payload was invalid: method `getSubscription` doesn't exist (contract getter is `subscriptionInfo`) and the `tvm.Slice` arg was a raw address string where toncenter v2 requires a **base64 BOC**; (c) unbounded HttpClient (100s default timeout) + keyless toncenter throttling stacked slow calls | Rebuilt payload: `subscriptionInfo` + minimal address→BOC slice serializer; named `"toncenter"` client with **8s timeout**; `CancellationToken` threaded through; `X-API-Key` wired from `TonCenter:ApiKey`/`TONCENTER_API_KEY`; non-200 → log status+body, skip user; stack parsing handles v2 pair-array form; tier mapping on uint8 codes (nanoton legacy fallback) | `Services/SubscriptionWorker.cs`, `Program.cs` | After `--no-cache` rebuild with flag unset: exactly one log line "SubscriptionWorker disabled", **zero** `Checking subscriptions...` lines, no starvation warnings. With flag deliberately true + key set: 200s, no 422s. Bot side: no `Engine API connection failed`, no price-alert `ConnectTimeout` |
| 2 | `ton_payment_monitor` restart-loops (4→60s), CPU → 100% at idle | With `TON_PAYMENTS_ENABLED=false` the loop logs "disabled" and **returns cleanly**; `_supervise` treated any return as "exited unexpectedly" and restarted forever | (a) `_supervise` now treats a clean return as **graceful exit — no restart**; (b) spawn site gated: `is_configured()` false → task never created | `main.py` | Boot with `TON_PAYMENTS_ENABLED=false`: one "monitor not started" info line, zero `exited unexpectedly` warnings, idle CPU single-digit |
| 3 | `❌ OpenRouter GPT connection test failed`, no reason given | Two clients, two bugs: `gpt/engine.py`'s test swallowed every error into a bare `False` (bare `except:`); `utils/openai_client.py` defaults to model `gpt-3.5-turbo`, which is not a valid **OpenRouter** slug (needs `openai/gpt-3.5-turbo`) → 404 behind "Using OpenRouter API" | New `GPTEngine.health_check()` returns `(ok, detail)` with endpoint, model, HTTP status and body head; startup logs the detail; OpenRouter slug auto-remap (+ `OPENROUTER_MODEL` override) with a warning | `gpt/engine.py`, `utils/openai_client.py`, `core/initialization.py` | Boot log shows either "GPT health check passed: HTTP 200 (…model=…)" or the exact failure (e.g. `HTTP 401 … Invalid API key`); a real message returns a completion |
| 4 | Moderation enabled, no usable key, **requests ALLOWED (unsafe)** | Code default is fail-closed, but **`.env` ships `MODERATION_FAIL_OPEN=true`** (and `.env.example` teaches it) — an explicit fail-open override with no key present | Flipped both files to `MODERATION_FAIL_OPEN=false` with a warning comment; fail-open remains an explicit, CRITICAL-logged opt-in | `.env`, `.env.example` | Boot with no key: CRITICAL line now says `effect="requests BLOCKED"`; a chat message gets the "safety check unavailable" reply, not an unmoderated answer. With a real `sk-` key: `moderation_ready` logged |
| 5 | "✅ Redis connection successful" but `analysis_cache: Using in-memory cache` | Two inits, two bugs: `CacheManager()` singleton was constructed with **no redis_url** (never even tried Redis); and `test_connections` ignored `ping()`'s return value (SafeRedisClient returns False instead of raising) so "successful" could lie | `CacheManager` now reads `REDIS_URL`, falls back to the shared `utils.redis_conn` connection, and logs the real error before any in-memory fallback (3s connect timeout); startup Redis test checks the ping return (INIT-003) | `services/analysis_cache.py`, `core/initialization.py` | Boot: `analysis_cache: Redis cache initialized (redis://redis:6379)` (or "reusing shared Redis connection"); the in-memory line appears only when Redis is genuinely down — with the reason |
| X | X/Twitter feature set | — | Full removal (inventory below) | 12 files | Clean boot: zero X-related lines; `grep -ri "tweepy\|X_API\|tweet_sentiment" --include="*.py" .` → only tombstones/changelog |

## X-removal inventory (verified before deleting)

**X-only — removed:** `handlers/X_handler.py`, `handlers/influencer_handler.py` (sole data source was `tweet_sentiment`), `services/X_monitor.py`, `services/tweet_sentiment.py` (importers: only the two removed handlers + 2 mini-app endpoints) — all four are now tombstone stubs pending `git rm`. Config keys `X_API_KEY/SECRET/ACCESS_TOKEN/ACCESS_TOKEN_SECRET/BEARER_TOKEN` removed from `core/config.py`, `.env`, `.env.example`, and `main.py` redact list. `initialize_X_monitor` + background start removed from `core/initialization.py`; `x_monitor` field removed from `AppContext`; `X_handler`/`influencer_handler` removed from `HANDLER_MODULES` (count is computed from the list — stays consistent, now 14 modules); X entries removed from `core/health.py`; `/X` + `/influencer` removed from `/help`; `tweepy` + `textblob` dropped from `requirements.txt`. Mini-app endpoints `/api/X/sentiment` and `/api/social` return an explicit "feature removed" payload (not 404) so old mini-app builds don't break.

**Shared — kept:** `services/analysis.py::process_sentiment_data` (generic aggregation, currently feedless — flagged, not deleted); the `@TonGPT_io` social link in `/support` (intentional). **No X-only DB tables exist** (models: User/Payment/ChatMessage/ActivityLog).

## Apply in order

**Terminal commands:**
```bash
# 1. The stale-image root cause of FIX 1 — non-negotiable:
docker compose build --no-cache tongpt-engine
docker compose build tongpt-bot

# 2. Finalize the X removal (tombstones → gone):
git rm handlers/X_handler.py handlers/influencer_handler.py services/X_monitor.py services/tweet_sentiment.py

# 3. Rebuild the bot venv without the dead deps (optional, cosmetic):
pip uninstall -y tweepy textblob

# 4. Boot and watch:
docker compose up
# expect: no 422s, no starvation warning, no monitor restart loop, no X lines,
#         "GPT health check passed" (or an explicit reason), moderation BLOCKED,
#         "analysis_cache: Redis cache initialized"

# 5. Commit:
git add -A && git commit -m "Launch fixes 1-5 + X removal (boot log 2026-07-03)"
```

**File edits (already applied by this pass):** `backend/TonGPT.Engine/Services/SubscriptionWorker.cs`, `backend/TonGPT.Engine/Program.cs`, `main.py`, `gpt/engine.py`, `utils/openai_client.py`, `core/initialization.py`, `core/config.py`, `core/health.py`, `services/analysis_cache.py`, `api/miniapp_server.py`, `bot/commands.py`, `.env`, `.env.example`, `requirements.txt`, plus 4 tombstones.

## Notes

- **`.env` contains live secrets** (bot token, API keys) and was seen during this pass. It should never be committed; rotate the bot token and API keys before public launch as standard hygiene.
- FIX 1's payload fix matters even though the worker is gated off: the register items ENG-006/ENG-007 are now closed at the code level. Do not enable `Subscription:EnablePolling` until the contract is deployed and audited (TOLK-001..003).
- Out of scope, untouched per instructions: Postgres unclean-shutdown recovery; no dependency upgrades; no refactors.
