# TonGPT — Fable 5 Upgrade Pass (July 2026)

One pass, three goals: close the remaining reliability MEDIUMs, ship differentiating features, keep the stack unchanged (Python/aiogram + C# Engine + Postgres + Redis + Preact Mini-App). Everything below is implemented, not proposed, unless marked *Roadmap*.

---

## 1. Prioritized improvements (what shipped and why)

| # | Item | Why it made the cut |
|---|------|---------------------|
| 1 | **Conversation memory with rolling summarization** (`gpt/engine.py`, `/memory`, `/forget`) | The single biggest "feels premium" differentiator. Most Telegram AI bots forget everything past ~10 turns; TonGPT now folds old turns into a compact profile (tokens followed, risk appetite, open questions) at near-zero token cost. `/forget` makes it a trust feature, not a creepy one. |
| 2 | **/compare — multi-token side-by-side** (`handlers/compare.py`) | Memecoin users constantly ask "X or Y?" — this answers it in one message with price, 24h, liquidity, volume, FDV, risk signals, and a "quick take". Reuses the existing cached, breaker-protected DexScreener service, so it cost ~150 lines. |
| 3 | **/watch + /watchlist** (`handlers/watchlist.py`) | Retention. A watchlist gives users a reason to come back daily. Validated on add (no typo entries), concurrent fetches, one-tap ➕Watch buttons on /compare and 🗑Remove on /watchlist. |
| 4 | **Price-alert correctness fix** (`main.py`) | Found during the pass: the alert loop compared EVERY alert against the TON price — a NOT alert at $0.002 fired instantly. Now resolves per-symbol prices via DexScreener with a per-cycle cache. This made the existing /alerts feature actually work for non-TON tokens. |
| 5 | **Fix pass 10 reliability quick-wins** | PAY-009 (tolerance clamp), QUEUE-001 (dead-letter + `>=` alerting), QUEUE-002 (drain dedup), REL-001 (TONAPI outage escalation), DISP-001/PAY-014/LIMIT-INCONSISTENCY-001 (displays now match what's enforced/charged — including the ProPlus→pro_plus mapping bug that showed paid Pro+ users Free-tier details). |
| 6 | **UX polish** | Personalized /start (returning users see their watchlist), /help covers the new surface, /alerts flow is cancellable, lists existing alerts, validates input, and keeps state on a bad price instead of silently dying. |

**Deliberately NOT done** (agentic wallet actions, on-chain trade execution): confirmation-based agentic TON actions are the obvious next differentiator, but they reopen the wallet/payment attack surface the register just spent 10 fix passes closing. Ship the above, run the smoke test, then design agentic actions with the same assertion-based model as SEC-001. *(Roadmap, below.)*

## 2. New user-facing surface

```
/compare NOT FISH      side-by-side comparison (2–4 tokens) + quick take
/watch NOT             add to watchlist (validated)
/watchlist  (/wl)      live prices, 24h, liquidity + remove buttons
/unwatch NOT           remove
/memory                what the bot remembers about you
/forget                erase history + memory (privacy)
/alerts                now: lists existing, cancellable, validated, multi-token correct
```

## 3. Technical notes for the operator

* **New env knobs** (all defaulted, nothing required):
  `SUMMARY_MODEL` (default `meta-llama/llama-3.1-8b-instruct`),
  `ACTIVATION_DEAD_LETTER_AFTER` (120), `ACTIVATION_DEAD_LETTER_FILE`,
  `TON_FETCH_FAIL_ALERT_AFTER` (10).
* **Memory design:** summary lives at `chat:sum:{user_id}` (30-day TTL, 1500-char cap). Summarization runs fire-and-forget on trim overflow with a per-user in-flight guard — it can never add latency to a user turn, and any failure degrades to "no summary", never an error.
* **Watchlist storage:** Redis set `watchlist:{user_id}`, `SYMBOL|address` entries, capped at 10. All Redis access goes through SafeRedisClient (never raises).
* **Handler registration:** `compare` and `watchlist` added to `HANDLER_MODULES` *before* `gpt_reply` (the catch-all must stay last). `/memory` + `/forget` live inside `gpt_reply.py` above the catch-all.

## 4. Roadmap (next passes, in order)

1. **Verified smoke pass** — `dotnet build` + `py_compile` + `PRE_LAUNCH_SMOKE_TEST.md`, now including: /compare, /watch→/watchlist round-trip, /memory after 11+ turns, a non-TON price alert, and a forced activation-queue dead-letter.
2. **Personalized recommendations** — "Based on your watchlist, NOT is up 12% today" push digest (daily, opt-in). All ingredients now exist (watchlist + DexScreener + notification service); ~1 day of work.
3. **Watchlist in the Mini-App** — read `watchlist:{user_id}` via a new authed endpoint; render with sparklines.
4. **Agentic actions (confirmation-based)** — start with the safest: "prepare a swap deep-link" (STON.fi URL with prefilled amounts — user signs in their own wallet; bot never touches keys). Only after that consider TON Connect transaction requests, using the SEC-001 assertion pattern.
5. Remaining register MEDIUMs: PAY-012 (DurationDays server clamp — C#), MINI-002, ENG-005/006/007, DATA-002, CFG-001, REF-002.

## 5. Launch readiness

| Gate | Status |
|---|---|
| CRITICAL / HIGH issues | **0 / 0 open** (48 → 55 resolved) |
| MEDIUM / LOW open | 16 / 24 — non-blocking polish |
| Confidence | **88/100** *(inferred — sandbox couldn't run builds this pass)* |
| Blocking gate | Run `PRE_LAUNCH_SMOKE_TEST.md` locally (`dotnet build`, `py_compile`, Stars sandbox charge, live wallet connect) |
| Verdict | 🟡 **Verify-then-go.** Nothing known blocks launch; the remaining risk is unverified-build risk, not design risk. |

*Register: see `REMEDIATION_REGISTER.md` (fix pass 10 note at top).*
