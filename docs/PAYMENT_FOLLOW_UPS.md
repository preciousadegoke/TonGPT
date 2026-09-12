# Payment follow-ups

Status recorded 2026-09-09. Fix 1 covers recipient verification. Fix 2 covers
checkpoint advancement and replay; the PostgreSQL restructuring is still pending.

- **Invalid wallet visibility.** `monitor_loop()` logs `ton_monitor_error` at
  error level when wallet validation raises, then retries after its interval.
  It does not send a separate operator notification. A regression test exercises
  the actual monitor loop and asserts that error. Missing wallet configuration
  already logs `ton_monitor_no_wallet` at warning level and disables the loop.
- **Fix 2 checkpoint recovery.** Checkpoint only after the entire scanned range
  has Engine-confirmed payments (including a payment ID), or non-payment /
  underpaid events. Queue acknowledgement and legacy Redis `ton_done` markers
  are not proof of activation. Failed requests, incomplete events and failed
  writes leave the checkpoint behind the gap. Page budgets retain a temporary
  backward cursor; restart replays from the last confirmed checkpoint.
  The old global `ton_monitor_high_lt` is deliberately ignored because it may
  already cover failures. The new checkpoint is scoped to wallet, network and
  API endpoint. Expect a history replay using unchanged `ton:event:action`
  Engine idempotency keys. No identifier or database migration runs in this fix.
  This fixes scanner retry/checkpoint behavior; end-to-end concurrency guarantees
  still require Fixes 3 and 4 and the later transaction-identifier migration.
- **Fix 2 / Fix 3 overlap checked (2026-09-12).** The Engine's faulty exception
  response has `alreadyProcessed: true` with `paymentId: null` when the matching
  payment does not exist. The real Python client preserves that missing ID.
  The TON monitor logs `ton_payment_unconfirmed_ack`, refuses checkpoint advance,
  and retries from the chain. Regression cases overlap a replay and a new payment,
  with either request receiving the false acknowledgement, then verify recovery.
  These simulate Engine responses through the real client; the actual EF/Postgres
  concurrent-request regression remains part of Fix 3. The shared activation queue
  still accepts `ok` without a payment ID and can drop its retry or notify falsely.
  TON's chain scan remains the recovery path; Stars has no equivalent chain scan.
  This protection does not resolve Fix 3 globally or Fix 4's renewal race.

- **Live payment history: open, not a Fix 1 blocker.** The user will confirm
  whether live payments were processed elsewhere and provide access if needed.
  The 2026-09-08 read-only query of `tongpt-postgres-dev` / `TonGPT` found zero
  Payments and 21 ActivityLogs, none for payment activation. This is a dev ledger
  and is not evidence about production payment history. Neither table nor the
  retained activity metadata contains receiving-wallet or network fields.
- **Production network configuration: non-urgent.** If production exists, check
  its bot and Engine settings. The inspected dev bot used the mainnet TONAPI
  endpoint while the Engine's TonCenter network setting was testnet. Confirm
  which verification paths are enabled and which network each actually queries;
  do not infer production settings from these dev containers.
- **Engine HTTP timeout: non-urgent.** Inspect `docker logs tongpt-engine`,
  including startup and EF migration messages. The 2026-09-08 probe connected
  to TCP port 5090 but timed out waiting 10 seconds for an HTTP response.
  A boot-time migration is a hypothesis, not a confirmed cause.
- **Stars queue durability: separate follow-up.** A temporary-file reproduction
  left an incomplete JSON line, then successfully enqueued a Stars activation.
  `_read_all()` skipped the combined malformed line and returned zero records.
  `fsync()` before enqueue returns does not prevent this lost-record case.
  Preserve the reproduction when addressing the queue; do not fold it silently
  into the TON restructuring.
- **Later restructuring boundaries.** Only TON scan progress and pending chain
  payments move to PostgreSQL. Stars retains its queue and Redis status functions;
  both methods use the shared transactional activation endpoint. Audit all shared
  callers and test the idempotent identifier migration against a backup copy
  before any live migration. The backup migration test has not been performed.
- **Regression plan.** Recipient rejection and failed persistence without
  checkpoint advance/restart replay are covered in Fixes 1-2. Concurrent duplicate
  notifications and concurrent renewal extensions remain required for Fixes 3-4.
  Keep the 16-test Tact subscription baseline as a regression check.
