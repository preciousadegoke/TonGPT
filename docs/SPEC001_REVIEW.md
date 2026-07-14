# SPEC-001 Phases 1–2 — Deep Review Report

| | |
|---|---|
| **Date** | 2026-07-14 (Finn Loop v2 /review) |
| **Scope** | `services/outcome_tracker.py`, `handlers/trackrecord.py`, `services/verdict.py` (hash), `main.py` (wiring), `handlers/verify.py` (handler removal), all tests |
| **Verdict** | ✅ **PASS** — 2 findings fixed during review, 4 risks accepted & documented |
| **Confidence** | High for scope. Production-ready pending the standing local `dotnet build` + live smoke test (unrelated to SPEC-001). |

## 1. Test results (full regression, run in review)

| Suite | Result |
|---|---|
| `tests/test_trackrecord.py` (P2) | ✅ 6/6 (incl. new F1/F2 regressions) |
| `tests/test_outcome_tracker.py` (P1) | ✅ 8/8 |
| `tests/test_rate_limiter.py` | ✅ 7/7 |
| `tests/test_payment_activation.py` | ✅ 4/4 |
| `tests/test_ton_payments.py` | ✅ 6/6 |
| `tests/test_ton_api_service.py` | ✅ 5/5 |
| jest `Subscription.spec.ts` (Tact contract) | ✅ 16/16 |
| `compileall` sweep (services/handlers/core/utils/gpt/bot/api/tests) | ✅ 0 errors |

## 2. Findings fixed during this review

- **F1 (UX/correctness, fixed):** `lookup_receipt` matched receipt *ids* only exactly,
  while hashes matched by prefix — a user typing the first 8+ chars of the id on a
  verdict card got "not found". Now: prefix match for both (≥8 hex chars enforced
  before any file I/O). Regression test added.
- **F2 (honesty, fixed):** catch-up evaluations (first run over a historical ledger)
  record under the schedule horizon ("30d") even when the verdict is much older.
  Every non-skipped outcome snapshot now stores `age_days` in its signals, so the
  record is self-describing. Regression test added.

## 3. Adversarial checks that PASSED (no change needed)

- **Sustainment integrity:** a dip-then-recovery can never finalize dead (needs two
  consecutive dead snapshots ≥72h apart); catch-up `skipped` markers carry no
  evidential weight; dead-only-at-30d with live 7d counter-evidence → `indeterminate`.
- **Idempotency:** re-running a pass inserts nothing (PK on verdict_id+horizon,
  byte-offset ledger cursor, torn-tail retry); outcome records never re-ingested.
- **Injection:** SQL fully parameterized; all attacker-influenced strings (token
  symbols = deployer-controlled DEX metadata, /proof queries) HTML-escaped with
  regression tests; non-hex /proof input rejected before any scan.
- **Failure isolation:** the loop never raises (supervised under MAIN-001 wrapper);
  fetch failures → `indeterminate`, never a guess; hashing failure never blocks a
  verdict; handler degrades to a friendly message if data layers are down.
- **Stats honesty:** microcap + indeterminate excluded from rates but counted and
  displayed; every published rate carries its denominator (property-tested);
  cold start invents no numbers.
- **Registration order:** `trackrecord` router before `verify`, both before the
  `gpt_reply` catch-all; duplicate `/receipts` handler removed.

## 4. Accepted risks (documented, revisit in Phase 3)

1. **`/proof` scans the whole JSONL per call.** Fine at current ledger size; no
   per-command rate limit beyond global middleware. Phase 3 should index hashes in
   SQLite (it needs them for Merkle proofs anyway).
2. **Canonical JSON = Python semantics.** Float repr and unicode handling follow
   Python's `json.dumps(sort_keys, separators=(",",":"))`. Third-party verifiers
   must replicate that. Acceptable: verification instructions say exactly this,
   and Phase 3's proof endpoint does the verification for users.
3. **Concurrent ledger appends** (verdict engine + outcome writer, same process)
   rely on small-append atomicity. Torn lines are already tolerated by every
   reader (skip + retry). Worst case is one lost outcome line, regenerable.
4. **Volume as activity proxy.** The spec's "swaps ≈ 0" is approximated by
   `volume_24h < $10` (DexScreener doesn't expose swap counts). Threshold is
   env-tunable (`OUTCOME_VOL_DEAD_USD`).

## 5. Standing environment caveats (pre-existing, not SPEC-001)

- `dotnet build backend/TonGPT.Engine` still requires a local run (no SDK in sandbox).
- `docs/PRE_LAUNCH_SMOKE_TEST.md` live checklist still open.
- OneDrive mount serves bash stale views of freshly-edited files; all shipped files
  were force-written through the mount and verified by compile+tests afterward.

## 6. Recommendation

Phases 1–2 are ready to merge. The tracker should run in production now so labels
start maturing — the track record is a time-locked asset and every day before
launch is a day of receipts lost. Phase 3 (Tolk anchor registry) is next and
should include: hash index in SQLite (kills risk #1), testnet soak, and the
sandbox contract spec per SPEC-001 §6-P3.
