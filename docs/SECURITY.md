# Security

Consolidated from `SECURITY_FIXES.md` + `CREDENTIAL_ROTATION.md`. The broader
legal/privacy/compliance review lives in [`PRODUCTION_AUDIT.md`](./PRODUCTION_AUDIT.md).

---

## 1. Credential rotation (do this if keys were ever committed)

Secrets must **never** be committed. `.env` is git-ignored; `.env.example` holds
placeholders only. If real keys were ever exposed (e.g. in a committed `.env` or
log), rotate **all** of them immediately:

- [ ] **Telegram Bot Token** — @BotFather → `/mybots` → your bot → API Token →
      *Regenerate*. Update `BOT_TOKEN` (and `TELEGRAM_TOKEN` if used).
- [ ] **OpenAI / OpenRouter keys** — regenerate in each provider dashboard.
      Update `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_MODERATION_API_KEY`.
- [ ] **X / Twitter keys** — regenerate in the developer portal. Update
      `X_API_KEY`, `X_API_SECRET`, `X_BEARER_TOKEN`, `X_ACCESS_TOKEN`,
      `X_ACCESS_TOKEN_SECRET`.
- [ ] **TON API keys** — request new keys. Update `TONAPI_KEY`, `TON_API_KEY`.
- [ ] **Redis password** — rotate via your provider. Update `REDIS_PASSWORD`.
- [ ] **Engine API key / webhook secrets** — rotate `ENGINE_API_KEY`,
      `WEBHOOK_SECRET`, `REFERRAL_SECRET`.

After rotating, scrub history if a secret was committed:
`git filter-repo` (or BFG) to purge the offending blob, then force-push and
invalidate the old keys regardless.

## 2. Practices baked into the codebase

- **Telegram initData HMAC** — every Mini-App API call is verified server-side
  (`verify_telegram_init_data` in `api/miniapp_server.py`).
- **Wallet ownership via ton_proof** — `/wallet/generate-payload` issues a nonce;
  `/wallet/auth` verifies the signed proof before binding a wallet.
- **Rate limiting** — per-tier limits via `core/rate_limiter.py` (env-tunable).
- **Moderation** — optional OpenAI moderation gate (`core/`, `services/moderation_service.py`).
- **Secrets in env only** — `.gitignore` blocks `.env`; `*.db` and `*.log` are
  ignored so runtime data/logs never get committed.

## 3. Reporting

Found a vulnerability? Do not open a public issue. Contact the maintainers
privately and allow time to patch before disclosure.
