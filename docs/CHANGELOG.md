# Changelog

Living history for TonGPT. Replaces the previous scattered set of fix/status
docs (`CHANGES.md`, `FIX_SUMMARY.md`, `FIXES_SUMMARY.md`, `README_FIXES.md`,
`VERIFICATION_REPORT.md`, `STATUS.txt`, `QUICK_START.md`, `INDEX.md`, and the old
top-level `CHANGELOG.md`). Full original text remains in git history.

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

---

## [Unreleased]

### Added
- **Mini-App v2** (`miniapp-v2/`): Preact + Vite + TypeScript rewrite of the
  Telegram Mini-App — TonConnect 2.0 with `ton_proof`, dual-rail checkout
  (TON Pay + Telegram Stars), live theme sync, MainButton/BackButton, skeletons,
  error boundaries, PWA. See `miniapp-v2/README.md`, `MIGRATION.md`, `LAUNCH.md`.
- Stars invoice backend endpoint drop-in: `miniapp-v2/server-additions/stars_invoice.py`.

### Changed
- Repo cleanup & tech-debt reduction (see `docs/CLEANUP_PLAN.md`): dead code
  removed, docs consolidated, `.gitignore` corrected, env file audited.
- Mini-App pricing aligned **exactly** to `core/pricing.py`
  (Starter 10 / Pro 30 / Pro+ 60 / Elite 120 TON).

### Removed
- `original_main.py`, dead `bot/handlers/` stub, committed `*.db` files, `bot.log`.
- 2 unused env keys: `REDIS_DB`, `TONCENTER_API`.

---

## Critical fixes — "5 blocking issues" (historical)

A set of blocking bugs were found and fixed across an earlier hardening pass.
Consolidated summary:

1. **Circular import** — `services/blockchain.py` imported from itself.
   Fixed to import from `utils.redis_conn`.
2. **Rate limiter async bug** — `await` was used on non-async Redis methods.
   Split into `_check_rate_limit_memory()` (sync fallback) and
   `_check_rate_limit_redis()`; the main method dispatches to the right one.
3. **Missing Redis methods** — added the missing `SafeRedisClient` methods so
   callers don't hit `NoneType` / attribute errors.
4. **API key routing** — OpenRouter vs OpenAI keys were mis-routed; corrected so
   each provider uses its own key.
5. **DexScreener 404 / data fetch** — fixed the token-data endpoint usage.
   Also cleaned up contradictory initialization logging.

All five were verified resolved (import smoke tests + manual runs) prior to this
cleanup. The original per-file before/after diffs are preserved in git history if
you need the exact line changes.

---

## Security & credentials

Security hardening and the urgent credential-rotation procedure now live in
[`docs/SECURITY.md`](./SECURITY.md). The full legal/privacy/compliance review is
in [`docs/PRODUCTION_AUDIT.md`](./PRODUCTION_AUDIT.md).
