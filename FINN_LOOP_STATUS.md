# FINN LOOP — Live Status

> Autonomous build/review loop dashboard. Updated after each major step.

| | |
|---|---|
| **Last updated** | 2026-07-14 (Finn Loop v2, session 1) |
| **Phase** | /build + /iterate → verification pass complete |
| **Awaiting** | 🚀 approval to finalize; `dotnet build` must be run locally |

## This session: verified build/smoke pass (the register's stated gap)

The `REMEDIATION_REGISTER.md` confidence was capped at "88/100 (inferred)" pending
a local build/smoke pass the previous environment couldn't run. This session ran it.

### Results

| Check | Result |
|---|---|
| `py_compile` sweep (97 files, incl. the 6 previously-stale) | ✅ 97/97 clean, 0 errors |
| `tests/test_rate_limiter.py` | ✅ 7/7 — after harness fix (see below) |
| `tests/test_payment_activation.py` | ✅ 4/4 — after harness fix |
| `tests/test_ton_api_service.py` | ✅ all pass |
| `tests/test_ton_payments.py` | ✅ 6/6 — after harness fix |
| `tests/Subscription.spec.ts` (Tact contract, jest) | ✅ 16/16 |
| `tests/SubscriptionTolk.spec.ts` | ⚠️ excluded from the suite (see below) |
| `dotnet build backend/TonGPT.Engine` | ⏳ **cannot run in sandbox** — run locally |

### Fixes made (test-harness drift, production code untouched)

1. **tests/test_rate_limiter.py** — `FakeRedis` had no `eval`, so the suite was
   silently exercising the degraded in-memory fallback instead of the RLIM-001
   atomic Lua path (and one assertion failed). Added a faithful Python emulation
   of `_ATOMIC_LUA`; all 7 tests now verify the real atomic check+consume.
2. **tests/test_payment_activation.py** — `FakeEngine.complete_payment` predated
   the `amount_stars` plumbing (pass 3/10); the queue's call raised TypeError and
   the drain never activated. Fake now mirrors the real signature. 4/4 pass.
3. **tests/test_ton_payments.py** — three drifts: `fake_fetch` lacked `before_lt`
   (PAY-007 pagination), and the expected idempotency key was pre-PAY-004
   (`ton:evX` → now `ton:evX:0`, per-transfer). 6/6 pass.
4. **jest.config.js** — excluded `SubscriptionTolk.spec.ts` (documented in-file):
   it tests a *planned* interface (`sendWithdraw`, exit codes 102/103) absent from
   `subscription.tolk` (ops: Subscribe/ChangeOwner/FeeNotice only) and deploys a
   mock empty code cell — it can neither compile nor exercise real TVM logic.
   Also added `modulePathIgnorePatterns` so jest's crawl skips `myenv/` etc.

### Remaining for a verified ≥90 confidence

- [ ] `dotnet build backend/TonGPT.Engine` locally (sandbox has no dotnet SDK and
      cannot install it — proxy blocks dot.net; no root for apt)
- [ ] `docs/PRE_LAUNCH_SMOKE_TEST.md` live checklist (bot + engine running)
- [ ] Open MEDIUM (16) / LOW (24) items in the register — cosmetic/consistency
      per pass-9 assessment, none correctness- or security-impacting

## Environment notes

- Sandbox: Linux, node 22 / python 3.10; **no dotnet**. Git available.
- OneDrive mount serves bash a **stale view of freshly-edited files** for a few
  minutes. Verified workaround: run copies from the outputs mount, re-verify from
  the project mount after sync. **Never `git add` a file whose mount view is stale.**
- Test-run recipe for contract tests (mount crawl is slow):
  copy `tests/` + `wrappers/` + configs next to a symlinked `node_modules` and run
  `node node_modules/jest/bin/jest.js tests/Subscription.spec.ts --runInBand`.

## Active spec

- **SPEC-001 — Receipts Engine** (`specs/SPEC-001-receipts-track-record.md`):
  outcome tracker → /trackrecord + /proof → Tolk anchor registry. Approved
  decisions: Tolk registry + Merkle proofs · /trackrecord surface · full
  calibration incl. misses · phased. **Phases 1–2 shipped** — outcome tracker +
  verdict_hash + supervised loop (9/9 tests); /trackrecord + /proof graded
  card with HTML-escape hardening (7/7 tests). **/review passed** —
  docs/SPEC001_REVIEW.md: 2 findings fixed (id-prefix lookup, age_days),
  4 risks documented, 52 checks green. Staged for merge — awaiting 🚀.
  Next: Phase 3 (Tolk anchor registry + Merkle proofs).

## History

- **2026-07-14** — Finn Loop v2 session 1: verification pass run; 4 test-harness
  drift fixes; jest config hardened; register confidence gap closed except the
  local dotnet build.
