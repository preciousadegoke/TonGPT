# TonGPT: Enterprise-Grade TON Blockchain Intelligence

![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)
![C# ASP.NET Core](https://img.shields.io/badge/C%23_.NET_Core-8.0-purple.svg)
![aiogram 3.4.1](https://img.shields.io/badge/aiogram-3.4.1-green.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Build: Passing](https://img.shields.io/badge/Build-Passing-brightgreen.svg)

TonGPT is a production-hardened AI intelligence agent built exclusively for the TON ecosystem, delivering live memecoin analytics, whale tracking, and on-chain insights via a dual Telegram Bot and Web Mini App interface. Designed for the TON AI Agent Hackathon 2026, it replaces generic LLM halluncination with hard data pipelines from TON API, DexScreener, and STON.fi. Rather than bolting AI onto a standard bot, TonGPT’s core is a context-aware OpenRouter GPT engine safeguarded by financial guardrails, backed by a C# infrastructure layer, and monetized via native Tact smart contracts.

---

## 🚀 Live Demo

- **Telegram Bot**: [@TonGPTBot] *(Placeholder)*
- **Mini App**: Available via `/app` command inside the bot.
- *Screenshot / GIF Demo: `![TonGPT Live Demo](docs/demo_placeholder.gif)`*

---

## ✨ Features

| Feature | Description | Status |
| :--- | :--- | :--- |
| **Pure TON Memecoin Analytics** | AI-driven token scanning, volume sorting, and aggressive filtering to ignore major cryptos. | ✅ Live |
| **Whale Monitoring** | Categorized whale analysis (Small to Mega) based on transaction volume via TON API. | ✅ Live |
| **DeFi Data Integration** | Real-time fetch of top STON.fi pools and live TON/USD cross-checks via CoinGecko. | ✅ Live |
| **Tact Subscription Contract** | Native TON payments for Starter (1 TON), Pro (5 TON), and Whale (20 TON) SaaS tiers. | ✅ Live |
| **Contextual GPT Engine** | OpenRouter + OpenAI pipeline injected with live market context strictly verified by APIs. | ✅ Live |
| **Financial Safety Guardrails** | AI middleware intercepts and flags deterministic financial advice ("100x", "guaranteed"). | ✅ Live |
| **Telegram Mini App** | Embedded Web UI (FastAPI/Nginx) with TON Connect authorization bindings. | ✅ Live |
| **GDPR Compliance Tools** | Fully operational `/export` and `/deletedata` flows for user data sovereignty. | ✅ Live |
| *FAISS Semantic Memory* | *Planned vector embedding layer for historical market memory.* | 🔧 Beta / Stubs |

---

## 🏗 Architecture

TonGPT leverages a distributed microservice architecture, separating the conversational AI layer from the heavy infrastructure backend and the blockchain logic.

```text
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│                 │       │                 │       │  OpenRouter /   │
│  Telegram User  │◄─────►│   aiogram Bot   │◄─────►│  OpenAI API     │
│  (Chat & Auth)  │       │  (Python 3.11+) │       │  (AI Engine)    │
│                 │       │                 │       └─────────────────┘
└─────────────────┘       └───────┬─────────┘                ▲
         ▲                        │                          │ Context
         │                   REST / API                      │
┌────────┴────────┐       ┌───────▼─────────┐       ┌────────▼────────┐
│                 │       │                 │       │  TON API /      │
│  Web Mini App   │◄─────►│ C# .NET Engine  │◄─────►│  STON.fi /      │
│  (Vue/Vanilla UI)       │ (PostgreSQL/DB) │       │  DexScreener    │
│                 │       │                 │       └────────┬────────┘
└─────────────────┘       └─────────────────┘                │
         ▲                        ▲                          │
         │                        │                          │
         └────────────────────────┴──────────────────────────┘
                        TON Blockchain (Tact Contracts)
```

| Layer | Component | Role |
| :--- | :--- | :--- |
| **Frontend** | Telegram Bot API / Mini App | High-throughput async handlers via `aiogram`; Vanilla JS/HTML Mini App with TON Connect. |
| **Application (AI)** | Python 3.11+ | OpenRouter GPT pipeline. Feeds strict real-time context (prices, volume) to the LLM. |
| **Infrastructure** | C# ASP.NET Core | Handles state management, subscription tracking, usage limits, and secure API routing. |
| **Data / Cache** | PostgreSQL + Redis | PgSQL for persistent state; Redis for hard rate limits, quotas, and API response caching. |
| **Smart Contracts**| Tact Language | Immutable tier-based subscription ledger deployed on TON (`Tep74` conformant patterns). |
| **Oracles/APIs** | TON API / STON.fi | Supplies live chain data, resolving DNS, jetton info, and top protocol yield pools. |

---

## 💎 TON Integration

TonGPT is natively woven into the TON ecosystem:

1. **Tact Smart Contracts (`contracts/subscription.tact`)**: 
   A strict, fail-closed payment state machine that accepts exactly 1, 5, or 20 TON, calculates 30-day expiries, and registers the subscription on the distributed ledger. Invalid payments automatically bounce.
2. **TON API pipeline (`services/tonapi.py`)**: 
   Implements an `EnhancedTONAPIClient` handling circuit breakers and exponential backoffs. It tracks raw blockchain events, resolves `.ton` DNS targets, and isolates large value transfers to classify wallet holder categories.
3. **STON.fi Data Feed (`services/stonfi.py`)**: 
   Fetches top pools directly from STON.fi, surfacing highest APY/TVL metrics contextually into the AI’s prompt generation.
4. **TON Connect**: 
   Integrated directly within the Mini App UI (`miniapp/`) allowing seamless wallet linking and authentication without leaving Telegram.

---

## 🧠 AI Capabilities

TonGPT focuses on grounded intelligence over hallucination:

- **Provider Routing**: Uses OpenRouter by default (handling multiple models smoothly) falling back to OpenAI dynamically.
- **Context Injection**: The GPT engine (`gpt/engine.py`) preemptively retrieves Top 15 trending memecoins + live TON metrics from caching logic prior to building the payload. The system prompt dynamically binds this data, ensuring the LLM replies accurately regarding immediate chain state.
- **Safety Middleware**: Post-processes all AI outputs, scanning for regulatory triggers. Output strings containing *"sure thing"*, *"100x"*, or *"guaranteed profit"* trip an intervention flag, prepending a strict financial risk disclaimer.

*(**Note**: FAISS semantic retrieval elements are currently being staged and remain in the roadmap for future ecosystem memory.)*

---

## 🛠 Tech Stack

| Domain | Technology | Purpose |
| :--- | :--- | :--- |
| **Bot Framework** | `aiogram`, `Python 3.11` | High performance asynchronous Telegram bot. |
| **Backend API** | `C# ASP.NET 8.0`, `FastAPI` | Core engine API, database abstractions, Mini App host. |
| **Smart Contracts** | `Tact`, `Blueprint` | Subscription management, native TON integration. |
| **Database** | `PostgreSQL 15`, `Redis 7` | Data persistence, multi-layer volatile cache. |
| **AI Access** | `OpenRouter`, `OpenAI` | Contextual reasoning and NLP parsing. |
| **Ecosystem Oracles**| `TON API`, `STON.fi`, `DexScreener`| Live chain states, token analytics. |
| **Deployment** | `Docker`, `docker-compose` | Containerized production and dev environment routing. |

---

## 📂 Repository Structure

```text
TONGPT/
├── backend/TonGPT.Engine/   # C# Backend dealing with core subscriptions and users
├── bot/                     # Core aiogram registration, handlers routing, and configuration
├── contracts/               # Tact smart contracts (subscription.tact) 
├── core/                    # Security, rate limiting, and initialization routines
├── gpt/                     # GPT engine, prompt overrides, and contextualizers
├── handlers/                # Telegram message routing (whale alerts, payments, info)
├── miniapp/                 # HTML/JS frontend loaded in Telegram Web App view
├── services/                # External integrations (TON API, STON API, caching logic)
├── utils/                   # Redis connection wrappers, live data scrappers, helpers
├── wrappers/                # TypeScript binding outputs built from Tact contracts
├── main.py                  # Entry execution, graceful startup/teardown
└── docker-compose.yml       # Dev and Prod multi-container orchestration
```

---

## 🏁 Quick Start

### Prerequisites
- Docker & Docker Compose
- Node.js (for Tact compilation)
- Python 3.11+
- An active Telegram Bot Token (`@BotFather`)

### Running Locally

**1. Clone & prepare environment**
```bash
git clone https://github.com/preciousadegoke/TonGPT.git
cd TonGPT
cp .env.example .env
```
Ensure the `.env` contains `BOT_TOKEN`, `OPENAI_API_KEY` or `OPENROUTER_API_KEY`, `TONAPI_KEY`, and a highly randomized 32-character `REFERRAL_SECRET`.

**2. Compile Contracts (Optional)**
```bash
npm install
npm run build
```

**3. Start the Ecosystem**
Using the provided multi-container topology:
```bash
docker-compose up -d --build
```
This orchestrates the C# Engine (`5090`), the Postgres/Redis datastores, the HTTP FastAPI Miniapp host, and the Python aiogram worker asynchronously.

### Validating
Once running, open Telegram:
- `/start` to see the contextual greeting.
- `/scan` to see the live TON DEX scanner filter.

---

## 🛡 Security & Audit

TonGPT passed a comprehensive security audit ensuring enterprise-grade protection:
- **Zero Fail-Open Paths:** Redis failures downgrade gracefully into local memory cache without halting core services or bypassing credit checks.
- **Economic Defenses:** Hard limits imposed per user against TON API targets.
- **Data Protection:** Implements standard right-to-erasure and GDPR portable packet generation via `/deletedata` and `/export`.
- **Infrastructure:** Refactored CORS bindings and secrets rotation parameters (`PRODUCTION_READINESS_AUDIT.md`).

---

## 🗺 Roadmap

Derived from current code stubs and ongoing implementations:
- Deploy the Tact subscription contract on Mainnet.
- Upgrade to full FAISS-backed persistent conversation state mapping.
- Finish Admin analytics tools and unified Twitter (X) influencer sentiment analysis flows.

---

## 📄 License

MIT License. See `LICENSE` for more information.
