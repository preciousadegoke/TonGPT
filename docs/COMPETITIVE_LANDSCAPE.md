# TON Competitive Landscape — Trading Bots & Mini-Apps (July 2026)

> Research pass for SPEC-002. Sources at bottom. Companion to
> `docs/CATEGORY_PLAY.md` ("radar, not cockpit") — this document tests that
> thesis against the mid-2026 field and locates the next wedge.

## 1. Execution bots (the cockpits)

| Player | Chains | Distinguishing features | Custody | Notes |
|---|---|---|---|---|
| **Not.Trade** | TON | Memescope real-time pair dashboard; insider safety panel (top-10 holders, snipers, dev movement, bundlers, LP lock); MCAP-trigger limit orders; multi-wallet sniping; MEV protection; Telegram mini-app + web terminal | Non-custodial (TON Connect) | The TON terminal of choice per DEXTools' 2026 guide; the safety panel is the closest in-product overlap with TonGPT |
| **Maestro** | 14 (incl. TON) | 573k+ users, $12.8B lifetime volume; MEV protection | Custodial | Breadth over depth; TON is one of many |
| **Crypton Superbot** | TON | Sniping, copy-trade, backup bots | Custodial | "Best TON sniper" per telegramtrading.net |
| Generic swap/sniper/copy/PnL bots | TON | 0.5–1% fee on top of DEX fee; STON.fi/DeDust routing | Mostly custodial | Category is mature and commoditized |

**Structural reads:**
- Execution is a solved, crowded, fee-compressed category. The dominant pattern is
  **custodial** — the guides themselves list "bot service holds your keys" and
  "phishing imposters" as top risks. Building a cockpit now = entering a knife fight
  over 0.5% fees against teams with years of head start. `CATEGORY_PLAY.md`'s
  "radar, not cockpit" verdict **survives contact with the 2026 field**.
- Not.Trade's insider safety panel shows safety features are becoming table stakes
  *inside* cockpits — but it's a point-in-time panel, not an accountable record.
  Nobody grades their own panel. TonGPT's receipts engine (SPEC-001) remains unique.

## 2. Analytics & safety (the radars — our lane)

| Player | What they ship | Accountability |
|---|---|---|
| **DYOR.io** | Trust Score (ML: regressions over on-chain params — volume, price action, mint rights), token explorer, **public API**, integration on TONScan.org, plus Minter/Presale products | **None published** — no hit-rate, no misses, no proofs |
| **Blocksafu** | TON token scanner / vulnerability scan / rug checker | None published |
| **Tonviewer / Tonscan** | Explorers; manual due-diligence surface | n/a |
| **GMGN** | Smart-money/wallet analytics, rug probability; TON presence minimal (SOL/EVM-first; GoPlus-dependent with accuracy disclaimers) | None published |

**Structural reads:**
- **DYOR.io is the closest direct competitor** and is playing a distribution game:
  API + explorer integrations put their score everywhere. TonGPT should expect
  "trust scores" to be ambient on TON within a year.
- **The receipts moat holds.** Nobody in this table publishes graded accuracy,
  misses, calibration, or tamper-evident history. SPEC-001 is still the only
  accountable radar. The counter-move to DYOR's distribution is making TonGPT's
  *track record* (not just the score) the thing that travels.

## 3. Mini-apps & platform primitives

- **Blum** — 43M MAU launchpad/DeFi hub, 45 chains, "AI-assisted strategies",
  Binance-Labs-backed. The gravity well of Telegram-native DeFi attention.
- **STON.fi / DeDust** — the DEX rails every bot routes through.
- **TON Pay SDK** (Feb 2026) — sub-second TON/USDT checkout for mini-apps;
  monetization rail relevant to TonGPT's subscription surface.
- **TON Agentic Wallets** (Apr 28, 2026) — **the big one.** Open-source,
  non-custodial standard: AI agents get dedicated smart-contract wallets that
  humans own; users set budgets and can revoke; ships with **MCP + CLI tools**,
  framework-agnostic. Explicit launch use case: *"trading bots operating within
  predefined budgets."*
- **Launchpads** — Tonpad (30-second memecoin launches, 0.5 TON), TON of Memes
  (gamified launches), Blum. A pump.fun-style firehose of new jettons — i.e. the
  scam supply chain TonGPT's Radar exists to grade.

**Structural reads:**
- Agentic Wallets is a *brand-new platform primitive with no safety layer*. Agents
  will ape into jettons within budget but with **zero token due diligence** — the
  standard governs *how much* an agent can spend, not *what it's safe to buy*.
  That gap is shaped exactly like TonGPT: a machine-readable verdict feed with a
  provable track record is the natural pre-trade gate for agent frameworks.
  `CATEGORY_PLAY.md` predicted this: *"nobody delegates money to an agent without
  a track record, and you'll have the only public one on the chain."* The
  primitive it needed now exists, with MCP as the integration surface.
- Launchpad feeds are a cheap Radar upgrade (verdict-at-birth for every launch),
  but it's incremental, not category-defining.

## 4. Threat matrix (what could hurt TonGPT)

1. **DYOR ships accountability.** If DYOR adds graded outcomes to Trust Score,
   the moat shrinks to our head start + on-chain anchoring. Mitigation: anchor
   NOW (operator runbook is ready), accumulate ledger days — time-locked assets
   can't be caught up.
2. **Not.Trade deepens its safety panel** into pre-trade blocking. They own the
   execution moment. Mitigation: be the *neutral* graded layer every cockpit can
   cite — a terminal grading its own panel is marking its own homework.
3. **Agent frameworks pick a default safety oracle.** Whoever becomes the
   pre-trade check for Agentic Wallets owns the next distribution channel.
   First-mover window is open **now** (standard is 10 weeks old). → SPEC-002.

## 5. Strategic conclusion

Do not build execution. Double down on the accountable-radar lane and claim the
agentic pre-trade gate while the window is open: **SPEC-002 — Guardian Gate, a
machine-readable verdict oracle for TON Agentic Wallets** (MCP-first), with the
SPEC-001 track record as its trust collateral.

## Sources

- DEXTools: Best TON Trading Bots 2026 — dextools.io/tutorials/best-ton-trading-bots-telegram-sniper-guide-2026
- DEXTools: Best TON Mini Apps 2026 — dextools.io/tutorials/best-ton-mini-apps-top-dapps-guide-2026
- telegramtrading.net: Best TON Sniper Bot 2026
- BingX: Top 7 Telegram Mini-Apps in the TON Ecosystem (2026)
- DYOR.io: Trust Score docs + TONScan integration announcement — dyor.io/blog/meet-dyor-trust-score, docs.dyor.io
- GMGN docs: CA security checks; DEXTools GMGN smart-money tutorial 2026
- CryptoBriefing / The Defiant / Forbes (2026-04-28): TON Agentic Wallets launch
- super-apps.ai (2026-02-09): TON Pay checkout SDK
- Tonpad, TON of Memes (ton.app/launchpads); Blocksafu TON scanner
