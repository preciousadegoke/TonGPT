# SPEC-002 — Guardian Gate: the Pre-Trade Safety Oracle for TON Agentic Wallets

| | |
|---|---|
| **Status** | 🟢 Phases 1–2 SHIPPED (2026-07-15) · Phase 3 pending · Phase 4 = operator |
| **Author** | Finn Loop (research + spec), approved by Legend |
| **Date** | 2026-07-15 |
| **Origin** | `docs/COMPETITIVE_LANDSCAPE.md` §3–5 + `docs/CATEGORY_PLAY.md` agentic endgame ("nobody delegates money to an agent without a track record") |
| **Depends on** | SPEC-001 (verdict engine, receipts ledger, outcome tracker, track record, anchoring) — ALL SHIPPED |
| **Window** | TON Agentic Wallets launched 2026-04-28 (open standard, MCP + CLI, explicit "trading bots within budgets" use case). **No safety layer exists for it yet.** First mover becomes the default pre-trade check. |

---

## 1. Refined feature description

TON's Agentic Wallets give AI agents budgeted, revocable, non-custodial wallets —
but the standard governs **how much** an agent can spend, not **what is safe to
buy**. Agents will ape into 30-second launchpad jettons with zero due diligence.

Guardian Gate makes TonGPT the missing safety layer: a **machine-readable
verdict oracle** any agent, bot, or mini-app can call before a trade —

1. **`GET /api/guardian/check/<address>`** (Engine-side, keyed): returns the
   structured verdict — risk level, named flags, liquidity/holder signals,
   receipt id + content hash, and **the caller-relevant track record**
   ("verdicts like this one were dead within 30d X% of the time (n/N)").
   A conservative `advice` field: `block | warn | pass` with explicit
   calibrated semantics (`pass` ≠ "safe"; it means "no major risk signals
   detected, historical false-negative rate Y% (n/N)").
2. **MCP server** (`scripts/guardian-mcp/`): the same check exposed as an MCP
   tool (`ton_token_safety_check`), because Agentic Wallets ship MCP tooling —
   agent developers add one server entry and every trade decision can consult
   TonGPT. This is the distribution wedge.
3. **Receipts for machines:** every gate check is itself ledgered (type
   `gate_check`, hashed, anchored daily like everything else) — so TonGPT can
   later publish "N agent trades screened, M blocked, of which K later rugged"
   — the first accountability loop FOR agent safety itself.

The moat compounds: DYOR can copy a score API; they cannot copy a graded,
on-chain-anchored history of gate decisions.

## 2. Research justification (see docs/COMPETITIVE_LANDSCAPE.md)

- Agentic Wallets: open standard, non-custodial, budgets/revocation, **MCP + CLI
  included**, framework-agnostic; launch materials name "trading bots operating
  within predefined budgets" as the first use case. No safety oracle exists.
- DYOR.io proves the distribution pattern (score API + integrations) but has no
  accountability; Not.Trade's safety panel is point-in-time, unaudited, and
  self-graded inside a cockpit with an execution conflict of interest.
- TonGPT uniquely holds: calibrated verdicts + graded outcomes + misses +
  anchored receipts (SPEC-001). Guardian Gate is that asset, packaged for the
  one consumer class that MUST be programmatic: agents.

## 3. Design

### 3.1 Gate semantics (calibrated, never binary-safe)

```jsonc
// GET /api/guardian/check/EQ...  (X-API-Key; per-key rate limits)
{
  "address": "EQ…", "symbol": "PEPE2",
  "risk_level": "high",                       // low|medium|high|unknown
  "advice": "block",                          // block|warn|pass (policy below)
  "flags": ["dev wallet 41%", "LP unlocked", "3 sibling deploys rugged"],
  "signals": {"liquidity_usd": 8100, "top_holder_pct": 41.2, "age_h": 3},
  "receipt": {"verdict_id": "a3f9…", "verdict_hash": "…", "ts": 1789450000},
  "track_record": {                            // the trust collateral, inline
    "bucket": "high",
    "observed_30d_death_rate": {"pct": 82.1, "dead": 23, "total": 28},
    "false_negative_rate": {"pct": 8.3, "dead": 1, "total": 12},
    "anchored_days": 41, "methodology": "https://…/METHODOLOGY.md"
  },
  "disclaimer": "risk signals, not guarantees; calibrated history attached"
}
```

Advice policy (env-tunable, documented in METHODOLOGY):
`block` = high risk OR unknown+unindexed; `warn` = medium OR data degraded;
`pass` = low with the false-negative rate attached. The gate NEVER says "safe".

### 3.2 Components

- **Engine endpoint** (`api/miniapp_server.py` or Engine C# — decide at build:
  the Python miniapp server already fronts verdict services and has IP limits;
  fastest path is Python, `GET /api/guardian/check`, reusing `check_token()` +
  `track_record_stats()` with a 60s per-token cache).
- **MCP server** (`scripts/guardian-mcp/`, Node, stdio): tools
  `ton_token_safety_check(address)` and `ton_track_record()`; thin HTTP client
  to the gate endpoint; ships with README for agent devs (Claude/GPT agent
  configs, Agentic Wallets CLI example).
- **`gate_check` ledger records**: address, advice, risk, caller key-id hash
  (never raw keys), ts, content hash → flows into the existing outcome tracker
  (was the blocked token later a rug? → the "we blocked K rugs for agents"
  headline) and daily Merkle anchoring, zero new infra.
- **/guardian upgrade**: the existing pitch command gains the API/MCP story.

### 3.3 Auth, rate limits, monetization

- Per-key auth (new `guardian_keys` table or env allowlist for v1); IP limiter
  already exists (RL-001 infra). Free tier: N checks/day (acquisition, same
  logic as verdict cards); paid tiers via existing subscription plans
  (`core/pricing.py` gains an `api` dimension later — NOT in v1 scope).
- Response includes `receipt` so a paying caller can audit any answer via /proof.

### 3.4 Edge cases & security

- Unindexed/very-new tokens → `advice: block` with `risk_level: unknown`
  ("no data is itself a signal") — agents must fail closed, and the gate's
  defaults teach that.
- Data-source outage → `warn` + `degraded: true`, never a fabricated pass
  (mirrors verdict engine rule 3).
- Address validation before any fetch (jetton master format); response caching
  keyed by canonical address to stop cache-poisoning via alias forms.
- The gate is read-only over existing services — no new money paths, no keys.
- Adversarial usage: scammers probing the gate to pre-test tokens is EXPECTED
  and fine — every probe is a ledgered receipt that improves the dataset.

## 4. Phased plan

| Phase | Deliverable | Effort |
|---|---|---|
| **1** | Gate endpoint (Python server) + gate_check ledgering + tests (advice policy matrix, fail-closed paths, cache, auth) | 2 sessions |
| **2** | MCP server + agent-dev README + example configs; /guardian text upgrade | 1–2 sessions |
| **3** | Gate accountability stats ("screened/blocked/confirmed") folded into /trackrecord + weekly digest | 1 session |
| **4** | Partnerships/distribution (Agentic Wallets ecosystem listing, Not.Trade/explorer integrations) — operator-led, spec provides the pitch page | n/a (operator) |

## 4.1 Phase 1 implementation notes (shipped)

- `services/guardian_gate.py` — `gate_check()` with the calibrated advice
  policy (unindexed/unknown/high→block, medium/degraded→warn, low→pass with
  the observed false-negative rate inline); per-token 60s cache (bounded);
  track-record block cached 5min with honest `insufficient_history` cold
  start; every check (cached included) appends a hashed `gate_check` receipt
  with the CALLER STORED AS A SHORT HASH, never raw. Address validation
  (friendly EQ/UQ/kQ/0Q + raw wc:hex) runs before any lookup or write.
- `api/miniapp_server.py` — `GET /api/guardian/check/{address}`: X-API-Key
  auth (`GUARDIAN_API_KEYS="name:key,…"`, keys ≥16 chars), per-key daily quota
  (`GUARDIAN_FREE_PER_DAY`, in-process v1 — documented), 400/401/429 error
  paths; sits behind the existing per-IP limiter middleware (RL-001).
- Pipeline integration: `outcome_tracker` ingestion skips `gate_check`
  records; `receipts_anchor` treats `gate_hash` as a Merkle leaf, so gate
  receipts are anchored daily like all others; `canonical_hash` excludes
  `gate_hash` for third-party re-verification.
- Tests: `tests/test_guardian_gate.py` — 9 checks: policy matrix, hostile
  address rejection, receipts + hash re-verification, FN-rate on pass,
  fail-closed unindexed, degraded warn, honest cold start, cache semantics,
  pipeline skip/leaf integration, auth + quota rollover.

## 4.2 Phase 2 implementation notes (shipped)

- `scripts/guardian-mcp/server.js` — **zero-dependency** MCP server (plain
  JSON-RPC 2.0 over stdio + Node ≥18 global fetch; one auditable file, nothing
  for agent devs to install). Tools: `ton_token_safety_check(address)` and
  `ton_track_record()`. Tool descriptions carry the calibrated semantics
  ("pass NEVER means safe") so the MODEL reading them learns the contract.
  **Every failure mode — network error, timeout, 5xx, quota — returns
  `isError` with "FAIL CLOSED: treat as block"**; the gate never fails open,
  end to end. `node server.js --selftest` exercises the full protocol
  (handshake, tools/list, pass/block round-trips, all error paths, ping,
  method-not-found) against mocked HTTP.
- `api/miniapp_server.py` — `GET /api/guardian/trackrecord` (keyed, but does
  NOT consume the check quota — reading the trust collateral is free):
  graded stats + maturing counts + methodology link; 503 (never fabricated
  data) when stores are unavailable.
- `scripts/guardian-mcp/README.md` — agent-dev onboarding: config JSON
  (Claude Desktop / Claude Code / generic MCP shape), Agentic Wallets usage
  instruction ("never buy on block"), failure-semantics contract, curl smoke.
- `handlers/verify.py` — /guardian now pitches the API + MCP server to bot
  and agent builders.

## 5. Acceptance criteria

1. **P1:** policy matrix tested (high→block, medium→warn, low→pass+FN-rate,
   unknown/unindexed→block, degraded→warn); every response carries receipt id +
   hash; gate_check records appear in the ledger, get hashed, and are picked up
   by the outcome tracker + anchor loop untouched; auth + rate limits enforced.
2. **P2:** MCP server passes the MCP inspector; a scripted agent session calls
   `ton_token_safety_check` end-to-end against a local gate.
3. **P3:** /trackrecord shows gate stats with denominators only when ≥1 gate
   check has a graded outcome.
