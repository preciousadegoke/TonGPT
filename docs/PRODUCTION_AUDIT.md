# TonGPT Production-Readiness Audit

**Audit type:** Legal, Privacy, Security & AI/Fintech Compliance  
**Scope:** Full codebase (Python bot, C# Engine, Mini-App, APIs)  
**Assumptions:** Real attackers, real regulators, global users, production reality  
**Date:** February 2026  

---

## SECTION A — 🔴 Critical Legal/Privacy Risks

### A1. Storage of personal data
| Finding | Severity | Detail |
|--------|----------|--------|
| **Chat messages stored indefinitely** | 🔴 High | `ChatMessage` in PostgreSQL has no retention TTL or automatic purge. User messages and AI responses are kept until explicit `/deletedata`. Privacy policy says "limited period" but implementation has no defined limit — **misalignment with policy and GDPR principle of storage limitation**. |
| **Wallet addresses in plaintext** | 🔴 High | `User.WalletAddress` and `WalletController` / `ActivityLog` metadata store addresses in plaintext. No use of `SecurityManager.encrypt_api_key()` for wallet storage. If DB is exfiltrated, wallet–TelegramId linkage is exposed. |
| **SQLite with PII** | 🟠 Medium | `notifications.db` (followed_wallets, user_notifications, notification_history) holds `user_id`, `wallet_address`, message content. Unencrypted at rest; file in project root. |

### A2. Wallet address handling
| Finding | Severity | Detail |
|--------|----------|--------|
| **Wallet auth API may be broken** | 🔴 High | `api/miniapp_server.py` calls `engine_client._request("POST", "/Wallet/auth", json=...)`. `EngineClient` has **no `_request` method** (only `_get`, `_post`, `_delete`). Wallet linking from Mini-App will raise `AttributeError` at runtime unless a wrapper exists elsewhere. |
| **Address in logs** | 🟠 Medium | `WalletController`: `_logger.LogInformation($"Authenticating wallet {authDto.Address} for user {authDto.TelegramId}");` — full address and TelegramId in application logs. Same in miniapp_server: `logger.info(f"Wallet {address[:20]}... linked to user {telegram_id}")` (partial is better but telegram_id is PII). |

### A3. Missing consent flows
| Finding | Severity | Detail |
|--------|----------|--------|
| **No explicit consent before processing** | 🔴 High | No in-bot or in–mini-app "I have read the Privacy Policy and Terms and agree" before storing TelegramId, username, chat history, or wallet link. Terms say "By using … you agree" (browse-wrap). For EU/UK and stricter jurisdictions, **explicit consent or clear contract acceptance** for processing is often required; implied consent is riskier. |
| **No consent for third-party AI transfer** | 🟠 Medium | User messages are sent to OpenRouter/OpenAI. Privacy policy mentions it but there is no explicit opt-in or "Continue" before first AI query that states data will be sent to third-party AI providers. |

### A4. Lack of disclaimers
| Finding | Severity | Detail |
|--------|----------|--------|
| **Programmatic disclaimer present** | ✅ | `AI_RESPONSE_DISCLAIMER` is appended to every AI response in `gpt/engine.py`. |
| **First-time / risky flows** | 🟡 | No disclaimer shown before first AI query or before payment (e.g. "Not financial advice; crypto is risky"). Terms/Disclaimer exist as documents but are not surfaced in-flow. |

### A5. Logging of sensitive data
| Finding | Severity | Detail |
|--------|----------|--------|
| **Unrestricted log file** | 🔴 High | `main.py`: `logging.FileHandler('bot.log', encoding='utf-8')` — all `logger.info/error` from all modules go to `bot.log`. Many handlers log `user_id`, `telegram_id`, wallet snippets, and error messages that can contain user input. No redaction, no log rotation config in code, no exclusion of PII. |
| **C# and Python logs** | 🟠 Medium | Backend logs wallet address and TelegramId in WalletController; Python logs similar. If logs are shipped to a third party or stored long-term, this is PII exposure and can conflict with data minimization. |

### A6. Hardcoded / default secrets
| Finding | Severity | Detail |
|--------|----------|--------|
| **C# appsettings default password** | 🔴 High | `appsettings.json`: `"Password=password"` in DefaultConnection. If env override is missing in production, DB uses weak default. |
| **WEBHOOK_SECRET empty default in dev** | 🟡 | `config.py`: `WEBHOOK_SECRET = WEBHOOK_SECRET or ""` — in non-production, empty string is accepted. Acceptable for dev only; ensure production enforces. |
| **Engine API key** | ✅ | No default in Python `engine_client`; backend middleware rejects when key not set. |

### A7. AI hallucination liability
| Finding | Severity | Detail |
|--------|----------|--------|
| **No guarantee language in UX** | 🟠 Medium | System prompt says "Never give financial advice" and disclaimer is appended, but there is no in-UI text such as "AI can make mistakes; verify important information." EU AI Act and similar regimes expect **transparency about limitations**. |
| **Context can amplify risk** | 🟡 | Real-time market context is injected into the prompt; if upstream data is wrong, model can propagate it. No "data may be delayed or inaccurate" in the immediate reply flow. |

### A8. Financial advice exposure
| Finding | Severity | Detail |
|--------|----------|--------|
| **Strong prompt + disclaimer** | ✅ | System prompt and programmatic disclaimer reduce risk. |
| **Tone of answers** | 🟡 | Model can still produce wording that reads as recommendation ("you could consider …"). No post-processing to detect or soften recommendation-like phrasing. |

### A9. Cross-border data issues
| Finding | Severity | Detail |
|--------|----------|--------|
| **No DPA or transfer mechanism stated** | 🔴 High | Privacy policy says "We may use cloud or hosting providers … that could be located outside your country. We require appropriate safeguards where legally required" but **no concrete safeguards** (e.g. SCCs, DPA with OpenRouter/OpenAI, Redis region) are documented or enforced in code. |
| **Redis / DB / AI provider location** | 🟠 Medium | If Redis or PostgreSQL or OpenRouter is in the US and users are in the EEA, transfers need a lawful basis and safeguards. No in-code or configurable region selection. |

---

## SECTION B — 🟠 Important Compliance Gaps

### User data & privacy
| Gap | Status | Notes |
|-----|--------|-------|
| Data minimization | 🟡 Partial | Only TelegramId, username, first/last name, wallet, plan, chat — minimal set. Payment records and activity logs add to scope. |
| Retention policy | 🔴 Missing | Policy says "limited period" and "removed or anonymized in line with our retention policy" but **no defined retention period or automated purge** for chat, activity logs, or notifications DB. |
| Right to deletion | ✅ Implemented | `/deletedata` and `DELETE User/data/{telegramId}` anonymize user and delete chat/activity. Payment records intentionally kept for legal/audit — document in policy. |
| Right of access/portability | ✅ Implemented | `/export` and `GET User/export/{telegramId}` return user data + chat history + activity. |
| PII in logs | 🔴 Yes | user_id, telegram_id, wallet (full or partial), and potentially message content in exceptions. |
| Encryption at rest | 🟠 Partial | PostgreSQL/Redis: not enforced in code (depends on infra). Wallet addresses and chat in DB not encrypted at application layer. |
| Encryption in transit | 🟡 Assumed | TLS depends on deployment; not enforced in application code. |
| Telegram ID handling | 🟡 | Stored as primary user key; acceptable. Logging and sharing with AI provider (in message content) should be documented and minimized. |

### AI regulation safety
| Gap | Status | Notes |
|-----|--------|-------|
| AI disclaimers | ✅ | Appended to every response. |
| No guarantee language | ✅ | Terms and Disclaimer state no guarantee of accuracy. |
| Uncertainty communication | 🟡 | Not explicitly prompted (e.g. "express uncertainty when unsure"). |
| Risk warnings on trading insights | ✅ | "Crypto investments are risky. Always DYOR." in disclaimer. |
| Prompt injection protections | 🟠 Weak | `security.sanitize_input()` exists (blocklist) but **is not used** before passing user message to GPT in `gpt_reply.py` / `gpt/engine.py`. Blocklist is bypassable (e.g. obfuscation, unicode). Parameterized queries used for DB; prompt injection is the main remaining vector. |

### Crypto / fintech compliance
| Gap | Status | Notes |
|-----|--------|-------|
| "Not financial advice" guardrail | ✅ | Prompt + disclaimer + Terms. |
| Wallet ownership verification | ✅ | `miniapp_server` implements ton_proof (nonce, timestamp, Ed25519 with PyNaCl). Backend accepts only `VERIFIED_BY_PYTHON_SERVER`. If PyNaCl missing, code allows through with warning — **should fail closed**. |
| Anti-abuse | ✅ | Rate limiting (AdvancedRateLimiter + decorator on GPT). |
| Rate limiting effectiveness | ✅ | Tier-based, Redis-backed, applied to AI endpoint. |
| Fraud vectors | 🟡 | Subscription upgrade gated by payment record. No KYC/AML; acceptable for current scale but should be documented as a known limitation. |

---

## SECTION C — 🟡 Architecture & Policy Alignment

| Principle | Alignment | Notes |
|-----------|-----------|-------|
| Privacy by design | 🟡 Partial | Minimal data collection and export/delete exist. Missing: retention automation, consent flows, encryption of sensitive fields, PII-safe logging. |
| Secure by default | 🟠 Partial | API key required for Engine; no default API key in Python. C# DB password default is weak. Secrets from env with production checks for some vars. |
| Least privilege | 🟡 | Bot and Engine have no fine-grained roles in code; deployment must restrict DB/Redis access. |
| Fail-safe defaults | 🟠 | Rate limiter fails open on error (availability over strictness). Wallet verification can pass without crypto if PyNaCl missing — should fail closed. |
| Observability for abuse | 🟡 | ActivityLog and monitoring exist. No dedicated abuse/anomaly detection or alerting on rate-limit violations. |
| Safe monetization | ✅ | Payment verification before upgrade; payment recorded before subscription change. |

**Terms alignment:**  
- TERMS.md §11: "Governed by the laws of **[Jurisdiction — to be specified by operator]**" — **placeholder not filled**. Must be set before production.  
- Refund policy referenced but not defined in repo.

---

## SECTION D — ✅ What Is Already Production-Ready

1. **Legal documents:** PRIVACY.md, TERMS.md, DISCLAIMER.md are substantive and cover data collected, no financial advice, liability limits, and user rights.
2. **User rights:** `/export` and `/deletedata` implemented; backend endpoints for export and erasure; policy references them.
3. **Payment integrity:** Subscription upgrade requires a valid payment record (Payment/record then Subscription/upgrade with paymentRecordId); no upgrade without proof.
4. **Wallet verification:** ton_proof verification in Python (nonce, timestamp, Ed25519 signature); backend only accepts server-verified proof string.
5. **AI disclaimer:** Programmatic disclaimer appended to every AI response.
6. **System prompt:** Instructs model not to give financial advice and to be educational.
7. **Rate limiting:** AdvancedRateLimiter with tier-based limits and decorator on GPT handler.
8. **API security:** Engine protected by API key middleware (constant-time comparison); Python client sends key when set.
9. **No default Engine API key** in Python; backend rejects unauthenticated requests when key is configured.
10. **Audit trail:** ActivityLog for subscription upgrade and wallet linking; payment recorded in DB.
11. **Input validation:** TON address format validated; payment amount validated with tolerance.
12. **WEBHOOK_SECRET:** Required in production (no default when ENVIRONMENT=production).

---

## SECTION E — 🛠️ Prioritized Fix Roadmap

### P0 — Must fix before public launch

| # | Item | Where | Action |
|---|------|--------|--------|
| 1 | Wallet auth broken | `api/miniapp_server.py` | Replace `engine_client._request("POST", "/Wallet/auth", json=...)` with `engine_client._post("Wallet/auth", {...})` (or add `_request` that delegates to `_post`). Verify end-to-end wallet link. |
| 2 | Chat retention vs policy | Backend / scheduler | Define retention (e.g. 90 or 365 days) and implement scheduled job or TTL to purge old ChatMessages and optionally ActivityLogs, or document "indefinite until deletion" and update policy to match. |
| 3 | PII in logs | All log call sites | Redact or remove telegram_id, user_id, wallet address, and user message content from log messages; or use structured logging with a PII filter and restrict log access. |
| 4 | Log file security | `main.py` | Add log rotation (e.g. RotatingFileHandler), do not write unredacted PII to bot.log, or disable file logging in production and use a safe logging backend. |
| 5 | C# default DB password | `appsettings.json` / deployment | Remove default password; require ConnectionStrings from environment or secret store in production; fail startup if not set. |
| 6 | Terms jurisdiction | TERMS.md | Replace "[Jurisdiction — to be specified by operator]" with the actual governing law and jurisdiction. |
| 7 | Consent / ToS acceptance | Bot / Mini-App | Add explicit step: e.g. "By continuing you agree to our Terms and Privacy Policy [links]. Type /accept or tap Accept." and store acceptance (timestamp + version); block wallet link and/or paid features until accepted. |

### P1 — Strongly recommended

| # | Item | Action |
|---|------|--------|
| 8 | Wallet storage encryption | Encrypt WalletAddress (and any other sensitive fields) at rest using SecurityManager; decrypt only when needed for display or on-chain checks. |
| 9 | Sanitize input before GPT | Call `security.sanitize_input()` (or a stronger prompt-injection control) on user message before sending to the model; consider allowlist or length/size limits. |
| 10 | PyNaCl mandatory for wallet auth | If nacl is missing, do not set `verification_passed = True`; return 503 or 403 and require PyNaCl for wallet linking. |
| 11 | Cross-border and DPAs | Document where Redis, DB, and OpenRouter/OpenAI process data; add DPAs or SCCs where required; state in Privacy Policy. |
| 12 | Retention automation | Implement retention job (e.g. delete ChatMessages older than X days; anonymize or delete old ActivityLogs per policy). |
| 13 | First-contact disclaimer | On first AI use or first payment, show short in-chat disclaimer: "Not financial advice. Crypto is risky. By continuing you agree to our Terms." |

### P2 — Future hardening

| # | Item |
|---|------|
| 14 | Optional consent for AI provider transfer (e.g. "Your messages are sent to [OpenAI/OpenRouter]. Continue?"). |
| 15 | Post-processing or classification to detect recommendation-like AI output and add extra disclaimer or block. |
| 16 | Encrypt or redact PII in ActivityLog metadata (e.g. wallet in wallet_linked). |
| 17 | SQLite encryption or migration of notifications data to main DB with access control. |
| 18 | Fail-closed option for rate limiter when Redis is down (configurable). |

---

## SECTION F — 🔐 Optional Hardening (Web3-Native)

| Recommendation | Purpose |
|----------------|--------|
| **ton_proof full chain** | Already done in Python. Optionally verify on C# side too (e.g. verify signature in Engine using public key and stored nonce) so compromise of Python does not allow fake VERIFIED_BY_PYTHON_SERVER. |
| **Signed session binding** | Bind Telegram session to a signed token (e.g. JWT with TelegramId + expiry) so miniapp requests cannot be replayed or forged without the bot-issued token. |
| **Encrypted wallet storage** | Encrypt WalletAddress in DB (and in ActivityLog metadata) with a key from HSM or env; decrypt only in trusted service. |
| **Abuse anomaly detection** | Track rate-limit hits, failed wallet proofs, and unusual request patterns; alert and optionally auto-throttle or block. |
| **AI output risk scoring** | Before sending to user, run a lightweight check (e.g. keyword/phrase list or small model) for high-risk phrases ("you should buy", "guaranteed returns"); add extra disclaimer or block. |
| **Data residency** | Allow configuration of Redis/DB region (e.g. EU) and document; prefer AI provider with EU option or DPA. |

---

## Summary

- **Critical:** Fix wallet auth call (`_request` → `_post`), align chat retention with policy and implement or document it, stop logging PII and secure bot.log, remove C# default DB password, set Terms jurisdiction, and add explicit consent/ToS acceptance.
- **Important:** Encrypt wallet at rest, sanitize/prompt-harden input to GPT, require PyNaCl for wallet link, document cross-border/DPAs, automate retention, and add first-contact disclaimer.
- **Strengths:** Legal docs, export/deletion, payment verification, ton_proof in Python, AI disclaimer, rate limiting, and API key protection are in place and production-oriented.

**Overall:** Not production-ready for a global, regulated launch until P0 items are closed and P1 items are planned. After P0 and key P1 items, the project is in a much better position for a controlled launch with clear risk acceptance on consent and cross-border transfers.
