# TonGPT

AI-powered intelligence for the TON ecosystem — live memecoin analytics, whale
tracking, and on-chain insights, delivered through a **Telegram Bot** and a
**Telegram Mini-App**, backed by a C# engine and native Tact smart contracts.

TonGPT replaces generic LLM guesswork with hard data pipelines (TON API,
DexScreener, STON.fi, CoinGecko) wrapped in financial-safety guardrails.

---

## Architecture at a glance

```
            ┌──────────────┐        ┌──────────────────────┐
 Telegram ──▶  aiogram bot  │        │  Telegram Mini-App    │
            │   (main.py)   │        │  (Preact, miniapp-v2) │
            └──────┬───────┘        └──────────┬───────────┘
                   │                            │ HTTPS + initData
                   ▼                            ▼
            ┌─────────────────────────────────────────────┐
            │      FastAPI mini-app server (api/)          │
            │  initData HMAC · ton_proof · payments        │
            └──────┬───────────────────────────┬──────────┘
                   │                            │
        ┌──────────▼─────────┐      ┌───────────▼───────────┐
        │  Python services   │      │   C# Engine (external) │
        │  TON/DEX/X/OpenAI  │      │   users, subscriptions │
        └──────────┬─────────┘      └────────────────────────┘
                   │
        ┌──────────▼─────────┐   ┌──────────────┐
        │  Redis (cache/RL)  │   │ Tact contract │  (contracts/)
        └────────────────────┘   └──────────────┘
```

| Layer | Where | Purpose |
| --- | --- | --- |
| Bot | `main.py`, `bot/`, `handlers/` | Telegram commands & callbacks (aiogram) |
| Mini-App API | `api/miniapp_server.py` | FastAPI: auth, payments, data endpoints |
| Mini-App UI | `miniapp-v2/` | Preact + Vite + TS front-end (see its own README) |
| Domain logic | `core/` | pricing (source of truth), rate-limit, security, config |
| Integrations | `services/` | TON API, DexScreener, STON.fi, OpenAI/OpenRouter, X |
| AI | `gpt/` | context-aware GPT pipeline + guardrails |
| Helpers | `utils/` | Redis client, formatting, realtime data |
| Contracts | `contracts/`, `tongpt-subscription/`, `wrappers/` | Tact subscription contract |

---

## Project structure

```
tongpt/
├── main.py              # bot + mini-app entrypoint (uvicorn on MINIAPP_PORT, default 8000)
├── api/                 # FastAPI mini-app server
├── bot/  handlers/      # Telegram command registration + handlers
├── core/               # config, pricing, rate-limit, security
├── services/  gpt/  utils/
├── contracts/          # Tact smart-contract code
├── miniapp-v2/         # Preact Mini-App (front-end)
├── scripts/  tests/    # ops scripts + test suite
├── docs/               # CHANGELOG, SECURITY, PRODUCTION_AUDIT, CLEANUP_PLAN, legal
├── Dockerfile  docker-compose*.yml
└── .env.example
```

> Cleaning up the repo? See **[docs/CLEANUP_PLAN.md](docs/CLEANUP_PLAN.md)** and
> the staged **[cleanup.sh](cleanup.sh)**.

---

## Development workflow

### 1. Backend (bot + API)

```bash
python -m venv myenv && source myenv/bin/activate   # Windows: myenv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # fill in real secrets (never commit)
python main.py                                       # bot + Mini-App API on :8000
```

Requires a running **Redis** (`REDIS_HOST/PORT/PASSWORD`) and the **C# Engine**
(`ENGINE_URL`, `ENGINE_API_KEY`).

### 2. Mini-App front-end

```bash
cd miniapp-v2
npm install
npm run dev      # http://localhost:5173, proxies /api → :8000
npm run build    # → miniapp-v2/dist (served by FastAPI in prod)
```

See `miniapp-v2/README.md`, `MIGRATION.md`, and `LAUNCH.md` for the full
Mini-App guide and launch checklist.

### 3. Smart contracts

```bash
npm install            # root: Tact/blueprint toolchain
npm run build          # compile the subscription contract
npm test               # jest contract tests
```

### 4. Docker (full stack)

```bash
docker compose up --build   # engine, bot, web-ui (nginx), postgres, redis
```

---

## Configuration

All config is via environment variables — see **`.env.example`** (audited; every
key is used). Highlights:

- **Secrets:** `BOT_TOKEN`, `OPENAI_API_KEY`/`OPENROUTER_API_KEY`, `TONAPI_KEY`,
  `ENGINE_API_KEY`, `REDIS_PASSWORD`, `X_*`. Never commit real values.
- **Payments:** `PAYMENT_TOKEN` (Stars), `PAYMENT_WALLET_ADDRESS` (TON),
  `TON_PAYMENTS_ENABLED`. Plan prices are defined once in `core/pricing.py`.
- **Tuning:** `RATE_LIMIT_*`, `DEX_*`, `TON_HTTP_*` (read via `_env_int/_float/_bool`).

If a secret was ever committed, rotate everything — see **[docs/SECURITY.md](docs/SECURITY.md)**.

---

## Documentation

| Doc | What |
| --- | --- |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Living change history |
| [docs/SECURITY.md](docs/SECURITY.md) | Security practices + credential rotation |
| [docs/PRODUCTION_AUDIT.md](docs/PRODUCTION_AUDIT.md) | Legal/privacy/compliance review |
| [docs/CLEANUP_PLAN.md](docs/CLEANUP_PLAN.md) | Repo cleanup plan + structure |
| `DISCLAIMER.md` · `PRIVACY.md` · `TERMS.md` | Legal pages (linked by the app) |

---

## License

MIT — see [LICENSE](LICENSE).

> **Not financial advice.** TonGPT provides informational analytics only.
> Memecoins are highly volatile and carry significant risk of loss.
