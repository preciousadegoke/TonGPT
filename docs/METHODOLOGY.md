# TonGPT Track-Record Methodology (public, versioned)

> This document is the public rulebook for every number on `/trackrecord`.
> Rules are versioned; any change is dated here BEFORE it affects published
> stats. That's the deal: you can't trust a score whose rules move silently.

**Version 1.0 — 2026-07-15** (SPEC-001 Phases 1–4)

## What gets graded

Every verdict TonGPT issues (via /check, forwards, Group Guardian, or Radar)
is written to an append-only ledger at the moment it's made, with a canonical
SHA-256 content hash. Each verdict is then re-checked at **T+24h, T+72h, T+7d
and T+30d** and its token labeled:

| Label | Operational criteria |
|---|---|
| `rugged` | liquidity −≥95% from verdict time AND (24h volume ≈ $0 OR price −≥90%), confirmed by **two consecutive snapshots ≥72h apart** |
| `collapsed` | price −≥90% AND volume ≈ $0, liquidity not clearly pulled (slow rug/abandonment), same confirmation rule |
| `alive` | ≥$1k liquidity and trading activity at T+30d |
| `microcap` | <$500 liquidity at verdict time — tracked, **excluded from all rates** (no padding wins with dust tokens) |
| `indeterminate` | market data unavailable, or death observable only at the final snapshot with live counter-evidence before it — **excluded from rates, count disclosed** |

Criteria follow the academic rug-pull detection literature (dead-token
definitions: sustained liquidity withdrawal + activity cessation + price
collapse, with recovery guards). Thresholds are env-tunable and their current
values are printed here; changing them bumps this document's version.

## The honesty rules

1. **A dip is never a rug.** Finalizing a dead label requires two dead
   snapshots ≥72h apart. A token that looks dead at 72h and recovers by 7d is
   `alive`. If the tracker was down and can't prove sustainment, the label is
   `indeterminate` — never claimed as a catch.
2. **Every rate ships its denominator.** "Flagged 34 of 41" — never just "83%".
3. **Misses are listed unprompted.** Tokens we rated 🟢/⚪ that died appear on
   the card with their receipt ids, before anyone asks.
4. **False alarms are a headline stat.** % of 🔴 calls still alive at 30d.
5. **Calibration over accuracy theater.** We publish the observed 30-day death
   rate per rating bucket, so you can see what 🔴 actually means historically.

## Verifiability

- Every receipt's canonical hash: SHA-256 over its JSON with hash fields
  removed, keys sorted, no whitespace (`/proof <id>` shows it).
- Each UTC day's receipt hashes form a sorted-pair SHA-256 Merkle tree; the
  root is written to an **append-only registry contract** on TON
  (`tongpt-subscription/contracts/anchor_registry.tolk`) — once a day's root
  is on-chain it cannot be rewritten, by anyone, including us.
- `/proof <receipt id>` serves the inclusion proof; verify it against the
  on-chain root with any SHA-256 implementation: repeatedly hash
  `sha256(min(a,b) ‖ max(a,b))` up the sibling path and compare to
  `getRoot(dayIndex)`.

## Known limitations (disclosed, not hidden)

- **Volume proxies activity.** DEX APIs don't expose swap counts; "activity ≈ 0"
  means 24h volume < $10 (`OUTCOME_VOL_DEAD_USD`).
- **Data gaps favor caution.** If the market API drops a dead pair, we
  corroborate before labeling; unprovable cases are `indeterminate`, not wins.
- **Canonical JSON is Python-semantics.** Third-party verifiers must serialize
  like `json.dumps(rec, sort_keys=True, separators=(",",":"), ensure_ascii=False)`.
- **The anchor lags the receipt.** Receipts are hashed at issuance; the day's
  root goes on-chain after the UTC day completes (operator-sent). A receipt is
  fully tamper-evident locally from second zero and chain-provable from the
  next day.

## Current thresholds (v1.0)

| Parameter | Value | Env override |
|---|---|---|
| Liquidity-pull threshold | −95% | `OUTCOME_LIQ_RUG_DROP_PCT` |
| Price-collapse threshold | −90% | `OUTCOME_PX_DEAD_DRAWDOWN_PCT` |
| Dead-volume threshold | <$10/24h | `OUTCOME_VOL_DEAD_USD` |
| Alive minimum liquidity | ≥$1,000 | `OUTCOME_ALIVE_MIN_LIQ_USD` |
| Microcap exclusion | <$500 at verdict | `OUTCOME_MICROCAP_MIN_LIQ_USD` |
| Evaluation schedule | 24h / 72h / 7d / 30d | (fixed) |
| Sustainment rule | 2 dead snapshots ≥72h apart | (fixed) |
