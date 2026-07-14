# SPEC-001 — The Receipts Engine: Outcome Tracking, Public Track Record & On-Chain Anchoring

| | |
|---|---|
| **Status** | 🟢 Phases 1–2 SHIPPED (2026-07-14) · Phases 3–4 pending |
| **Author** | Finn Loop (idea + research), approved by Legend |
| **Date** | 2026-07-14 |
| **Origin** | `docs/CATEGORY_PLAY.md` Move 2 — "the on-chain receipts ledger + public track-record page… it *is* the moat" |
| **Depends on** | Verdict engine (`services/verdict.py`, shipped), receipts ledger JSONL (shipped), Radar (`services/radar.py`, shipped) |
| **Decisions locked** | Anchoring: **lightweight Tolk registry + Merkle proofs** · Surface: **/trackrecord bot command** · Metrics: **full calibration incl. misses** · Scope: **full Move 2, phased** |

---

## 1. Refined feature description

Today TonGPT issues verdict cards ("🔴 High risk: dev wallet 41%, LP unlocked") and appends
each to an append-only JSONL ledger. **Nothing ever checks whether the call was right.**
This spec turns the ledger into a self-grading, publicly verifiable track record:

1. **Outcome Tracker** — a background job revisits every ledgered verdict on a schedule and
   labels the token's fate (`rugged` / `collapsed` / `alive` / `indeterminate`) using
   operational criteria from the rug-pull detection literature (§3.2). Labels are written
   back to the ledger as separate outcome records (the original verdict is never mutated).
2. **Track Record surface** — `/trackrecord` renders a shareable card: headline recall
   ("flagged 34 of 41 rugs early"), **and the misses** (false-alarm rate, the rugs we
   green-lit), plus a calibration table ("of tokens we rated 🔴, 82% were dead in 30 days").
   Full honesty is the differentiator: every number includes its denominator.
3. **On-chain anchor** — every verdict and outcome record is hashed into a daily Merkle
   tree; the root is stored in a **minimal Tolk registry contract** (one op: `Anchor(root)`,
   owner-gated, append-only day→root mapping + getter). Anyone can verify any historical
   verdict card against the chain with the Merkle inclusion proof the bot serves on demand.
   Result: the track record is provably not back-dated — the one asset a well-funded
   copycat cannot buy.

## 2. Why this (research summary)

- **White space confirmed.** No competitor publishes accountable accuracy. GMGN's rug/honeypot
  signals are third-party (GoPlus) with explicit "no guarantee of timeliness or accuracy"
  disclaimers; RugCheck, TokenSniffer, Blocksafu and the TON-specific scanners publish
  scores but **no public hit-rate, no misses, no proofs**. A timestamped, on-chain-anchored
  accuracy page is a category-level differentiator, exactly as `CATEGORY_PLAY.md` argued.
- **Auto-labeling is a solved research problem.** Recent literature (TM-RugPull dataset;
  ScienceDirect DEX rug-pull studies) converges on operational criteria: near-total
  liquidity withdrawal, cessation of on-chain activity, and price/volume collapse
  **persisting >72h** ("dead token"), with maximum-drawdown + recovery checks to avoid
  mislabeling a dip as a rug. We adopt these thresholds (§3.2) rather than inventing our own.
- **Anchoring pattern is standard.** OpenTimestamps/OriginStamp-style: aggregate thousands of
  hashes into one Merkle root, anchor the root once daily, store inclusion proofs off-chain.
  Cost on TON: one tiny internal message/day (pennies). The Tolk registry adds queryability
  (`getRoot(day)`) over the tx-comment approach, at the cost of one ~100-line audited-by-us
  contract.
- **Calibration beats headlines.** Brier-score practice (meteorology → superforecasting):
  publish *"of our N% risk calls, how many happened"* buckets. It is strictly harder to
  game than a hit count, survives one loud false-negative, and no crypto competitor does it.

## 3. Design

### 3.1 Data model (extends the existing JSONL ledger — no migration)

New record types appended to the same ledger (and mirrored to SQLite for queries):

```jsonc
// outcome record (one per verdict per evaluation)
{"type": "outcome", "verdict_hash": "<sha256 of canonical verdict json>",
 "token": "EQ…", "checked_at": 1789450000, "age_days": 7,
 "label": "rugged|collapsed|alive|indeterminate",
 "signals": {"liq_usd": 12.4, "liq_drop_pct": 99.7, "px_drawdown_pct": 99.9,
              "swaps_24h": 0, "dead_for_h": 96},
 "verdict_risk": "high|medium|low"}   // copied for calibration bucketing

// anchor record (one per day)
{"type": "anchor", "day": "2026-07-14", "merkle_root": "…", "count": 412,
 "tx": "<ton tx hash>", "contract": "EQ…"}
```

- `verdict_hash` = SHA-256 over a **canonical JSON serialization** (sorted keys, fixed
  float formatting) of the verdict record. Hash computed at write time and stored on the
  verdict record too, so cards can print a short proof id (`#a3f9…`).
- SQLite (`data/receipts.db`) is a derived index (rebuildable from JSONL) — JSONL stays
  the source of truth, consistent with the activation-queue durability philosophy.

### 3.2 Outcome labeling rules (from literature, tuned for TON/DEX data we already fetch)

Evaluation schedule per verdict: **T+24h, T+72h, T+7d, T+30d** (then stop).
Data source: DexScreener pair data (already integrated) + TONAPI activity.

| Label | Criteria (all sustained ≥72h except where noted) |
|---|---|
| `rugged` | liquidity dropped ≥95% from level at verdict time AND (24h swaps ≈ 0 OR price drawdown ≥90%) |
| `collapsed` | price drawdown ≥90% + volume ≈ 0, but liquidity not clearly pulled (slow rug / abandonment) |
| `alive` | pair still has ≥$1k liquidity AND nonzero daily swaps at T+30d |
| `indeterminate` | data unavailable (pair delisted from API, token migrated) — **excluded from accuracy stats, but counted and shown** |

Guards: recovery check (if liquidity/price recovers within the window, not a rug — the
literature's RC criterion); minimum baseline (tokens with <$500 liquidity at verdict time
are labeled `microcap` and excluded from headline stats to avoid padding wins).

### 3.3 Scoring & the /trackrecord card

- **Recall (headline):** of tokens later labeled `rugged|collapsed`, % that had 🔴/🟠 at verdict time, split by horizon (24h/7d/30d).
- **False-alarm rate:** of 🔴 verdicts, % still `alive` at 30d — printed on the card, not buried.
- **The misses:** count + linked list of 🟢/🟡 verdicts that rugged (each with its receipt hash). Shown before anyone asks.
- **Calibration table:** risk-tier buckets → observed 30-day death rate. (Future: proper Brier score once risk is emitted as a probability.)
- Card footer: `📜 412 verdicts anchored · root a3f9… · verify: t.me/<bot>?start=proof_<hash>`
- `/proof <hash>` (or deep-link) returns the Merkle inclusion proof + contract address + day, with a one-paragraph "how to verify" explainer.

### 3.4 Tolk anchor registry (minimal by design)

```
storage: owner: address, roots: map<uint32 dayIndex, uint256 root>
ops:     Anchor(dayIndex, root)  — owner only; throws if dayIndex already set (append-only)
getters: getRoot(dayIndex), getOwner()
```

- **~100 lines, no funds held, no user interaction** — the entire attack surface is "can a
  non-owner write a root" and "can a root be overwritten"; both unit-tested in sandbox.
  This sidesteps the unaudited-subscription-contract problem (TOLK-001..003): the registry
  contract holds no money and gates no product features.
- Anchor job: daily at 00:10 UTC; build tree over all records of the prior UTC day; send
  `Anchor`; append the anchor record with the tx hash; alert via `error_reporter` on failure
  (missed days are anchored retroactively next run — dayIndex keying makes this safe).
- Merkle: SHA-256, sorted-pair hashing (proof verification needs no left/right flags);
  proofs generated on demand from JSONL (nothing extra stored).

### 3.5 Integration points

- `services/outcome_tracker.py` (new) — evaluation loop, runs under the existing
  `_spawn_supervised` wrapper (MAIN-001 pattern).
- `services/receipts_anchor.py` (new) — Merkle build + Tolk send via existing wallet infra.
- `services/verdict.py` — add `verdict_hash` at write; card footer gains proof id.
- `handlers/trackrecord.py` (new) — `/trackrecord`, `/proof`.
- `tongpt-subscription/` sibling: `contracts/anchor_registry.tolk` + sandbox spec
  (pattern proven by `Subscription.spec.ts` 16/16).

## 4. Edge cases, security, performance

- **Data gaps:** DexScreener drops dead pairs — exactly the tokens we must label. Mitigate:
  snapshot liquidity/price *at verdict time* (already in the verdict record); on API-miss at
  eval time, corroborate with TONAPI activity before labeling `indeterminate`.
- **Fake-recovery gaming:** dev re-adds dust liquidity to dodge the 95% rule → the sustained-72h
  requirement + swap-count check defeats dust revivals.
- **Jetton identity spoofing:** track by Jetton master address only (never name/symbol) —
  fake-twin tokens are a documented TON scam vector.
- **Metric gaming (self):** microcap exclusion + indeterminate disclosure prevent padding;
  all rules versioned in the spec so methodology changes are public and dated.
- **Anchor key compromise:** worst case = attacker writes bogus roots for *future* days; past
  roots immutable (append-only). Owner key = existing payment-wallet ops discipline; rotation
  via `ChangeOwner` op (same pattern as subscription contract).
- **Legal/comms:** cards keep calibrated language ("high risk", never "scam"/"safe" as fact) —
  consistent with the red-team note in `CATEGORY_PLAY.md`; the misses list is the honesty proof.
- **Performance:** ≤ a few hundred verdicts/day → eval loop is trivially cheap (4 API calls per
  verdict lifetime, batched); Merkle build O(n log n) over one day's records; SQLite index
  keeps `/trackrecord` render <100ms with zero JSONL scans on the hot path.
- **Privacy:** ledger contains token data only, no user ids in anchored records.

## 5. Phased implementation plan

| Phase | Deliverable | Effort | Ships alone? |
|---|---|---|---|
| **1 — Outcome Tracker** | `outcome_tracker.py` + SQLite index + labeling rules + unit tests (fixture-driven: rug/dip-recovery/slow-rug/microcap/api-gap cases) | ~2–3 sessions | ✅ starts accruing labels immediately (the time-locked asset) |
| **2 — /trackrecord + /proof** | Handler + card renderer + calibration table + misses list + tests | ~1–2 sessions | ✅ (proof shows "anchoring pending" until Phase 3) |
| **3 — Tolk anchor registry** | Contract + sandbox spec + `receipts_anchor.py` + daily job + retro-anchoring | ~2 sessions + testnet soak | ✅ |
| **4 — Polish** | Radar-channel weekly receipts digest; verdict-card footer proof ids; `docs/` methodology page | ~1 session | optional |

Phase order is deliberate: **labels take calendar time to mature** (30-day horizon), so the
tracker ships first even though the shiny parts are 2–3.

## 5.1 Phase 1 implementation notes (shipped)

- `services/outcome_tracker.py` — labeling per §3.2; SQLite index (`data/receipts.db`,
  rebuildable); byte-offset JSONL ingestion (torn-tail safe); injectable clock +
  market fetcher; `MAX_FETCH_PER_PASS` backpressure (default 200/pass); catch-up
  after downtime marks missed horizons `skipped` so one instant can never fake a
  ≥72h sustained confirmation; final outcomes appended to the ledger with
  `outcome_hash`. `track_record_stats()` ships recall, false-alarm rate, misses
  list and calibration buckets — every rate with its denominator.
- `services/verdict.py` — every new verdict record now carries `verdict_hash`
  (canonical SHA-256, §3.1) — the future Merkle leaf.
- `main.py` — `outcome_tracker` runs under `_spawn_supervised`
  (`OUTCOME_TRACKER_ENABLED=false` to disable).
- Tests: `tests/test_outcome_tracker.py` — 9 tests / 7 archetypes green, incl.
  dip-recovery guard, idempotent re-run, downtime integrity, backpressure.

## 5.2 Phase 2 implementation notes (shipped)

- `handlers/trackrecord.py` — `/trackrecord` (+ `/receipts` alias) graded card:
  recall, false-alarm rate, misses list (real receipt ids), calibration table,
  exclusions — every rate with its denominator; graceful cold start (issued
  counts + maturity note, no invented rates). `/proof <id|hash-prefix>` shows
  the receipt, its canonical hash, graded outcome, and an explicitly *pending*
  anchor status until Phase 3. Renderers are pure functions (testable sans
  aiogram). All attacker-influenced strings (token symbols = deployer-controlled
  DEX metadata, user queries) are HTML-escaped.
- `services/outcome_tracker.py` — added `pending_counts()` and
  `lookup_receipt()` (verdict_id exact / ≥8-hex-char hash prefix; hostile
  non-hex input rejected before any file scan).
- `handlers/verify.py` — old issued-counts-only `/receipts` handler removed;
  `main.py` registers `trackrecord` before `verify`.
- Tests: `tests/test_trackrecord.py` — 7 checks incl. denominator-sum property,
  HTML-injection regression, hostile lookup inputs.

## 6. Acceptance criteria (per phase)

1. **P1:** given a fixture ledger of 6 archetypal token histories, the tracker emits the 6
   expected labels; a dip-then-recovery token is NOT labeled rugged; re-running is idempotent.
2. **P2:** `/trackrecord` renders with zero outcomes (graceful cold start), with mixed data,
   and its stated denominators always sum; the misses list links real receipt hashes.
3. **P3:** sandbox: non-owner `Anchor` rejected; duplicate day rejected; `getRoot` round-trips;
   a served Merkle proof verifies against the stored root for a random ledger record; a
   skipped day is retro-anchored on the next run.

## 7. Research sources

- GMGN CA security checks (third-party data disclaimer): docs.gmgn.ai/index/ca-security-checks
- RugCheck / TokenSniffer / Blocksafu TON scanner (no published accuracy): rugcheck.xyz, tokensniffer.com, blocksafu.com/ton-token-scanner
- Rug-pull operational definitions & dead-token criteria: ScienceDirect S2096720925000028, S2096720925000636; TM-RugPull (arxiv 2602.21529); LROO detector (arxiv 2603.11324)
- Merkle anchoring / trustless timestamping practice: stampd.org/opentimestamps-trustless-proof, originstamp.com blockchain-timestamp guides
- Brier score & calibration for public track records: verdoso.com Brier notes; Grokipedia Brier score; arxiv 2305.03780 (boldness-recalibration)
