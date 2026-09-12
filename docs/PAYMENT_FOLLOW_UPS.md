# Payment follow-ups

Status recorded 2026-09-12. Fix 1 covers recipient verification, Fix 2 checkpoint
advancement/replay, and Fix 3 unconfirmed persistence failures. Fix 4's concurrent
renewal change is implemented for review; PostgreSQL restructuring remains pending.

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
  also depend on Fix 4 (now implemented for review) and the later
  transaction-identifier migration.
- **Fix 2 / Fix 3 overlap checked (2026-09-12).** Before Fix 3, the Engine's faulty
  exception response had `alreadyProcessed: true` with `paymentId: null` when the matching
  payment does not exist. The real Python client preserves that missing ID.
  The TON monitor logs `ton_payment_unconfirmed_ack`, refuses checkpoint advance,
  and retries from the chain. Regression cases overlap a replay and a new payment,
  with either request receiving the false acknowledgement, then verify recovery.
  These simulate Engine responses through the real client; Fix 3 now also tests
  the actual EF/Postgres concurrent-request path. The shared queue still trusts
  `ok` without checking the payment ID itself. Fix 3 removes this false success
  from the shared endpoint; its HTTP 503 follows existing client/queue retry
  handling for both TON and Stars. The TON scan's additional guard remains useful
  while an older Engine is deployed. Fix 4 addresses the renewal race below.
- **Fix 3: confirm a duplicate before acknowledging it.** After a failed save,
  re-query by `(ExternalId, Provider)`. Return `AlreadyProcessed` only with the
  matching persisted payment ID; otherwise log the failure and return retryable
  HTTP 503. Real PostgreSQL regressions cover concurrent duplicate notifications,
  different payments racing to create a user, and a general write failure. They
  reproduced two failures before the change and pass 3/3 afterward, including
  successful retry, no partial audit/payment writes, and idempotent replay.
  `scripts/test_payment_controller.py` runs them in a disposable PostgreSQL 15
  container; it does not use application data or run identifier migrations.
- **503 retry audit (2026-09-12).** `_post()` converts HTTP 503 into an integer
  error; `EngineClient.complete_payment()` retries three total attempts with
  1-second and 2-second waits, then returns a non-permanent failure. Both
  `handlers/pay.py::_activate_with_resilience` (Stars) and the TON monitor enqueue
  transient failures. `main.py` starts the supervised activation reconciler;
  its default drain interval is 60 seconds. TON also retains its checkpoint and
  retries the unconfirmed chain range. New Python regressions exercise the real
  client HTTP-status handling and queue drain for both providers through outage
  and recovery, using a fake HTTP transport and temporary files.
  Default queue thresholds alert every 10 failed drains and move an item to the
  dead-letter file after 120. These entries require manual recovery. If Stars
  queue insertion itself fails, the handler logs `ACTIVATION_LOST_RISK`; there is
  no automatic recovery in that branch. Track this with the separate Stars queue
  durability follow-up, not as part of the renewal or TON restructuring work.
- **Fix 4: concurrent renewal durations accumulate.** The previous tracked-entity
  calculation let two payments read one expiry and overwrite each other's time.
  `ExecuteUpdateAsync` now computes `max(current database expiry, now) + duration`
  under PostgreSQL's row lock. An explicit transaction contains payment/audit
  persistence and this update; rollback completes before Fix 3 rechecks a
  duplicate. Reload the tracked user before commit for the response expiry.
  The disposable PostgreSQL suite passes 8/8: previous Fix 3 cases, concurrent
  mixed TON/Stars renewals with future/expired/null expiry, duplicate renewal,
  and rollback after the actual expiry update followed by idempotent retry.
  All three distinct-payment renewal cases failed against the pre-fix controller.
  No schema change or identifier migration is part of this fix.
- **Engine authentication verified (2026-09-12).** The bot, Engine, and local
  `.env` credentials match. A read-only status request returns HTTP 401 without
  credentials and HTTP 200 with `X-Api-Key` or `Authorization: Bearer`. The running
  bot's actual `EngineClient` also succeeds. `EngineApiKey` is a configuration
  name, not an HTTP header. The earlier 401 probe omitted authentication.

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
- **Regression plan.** Recipient rejection, failed persistence without checkpoint
  advance/restart replay, and concurrent duplicate notifications are covered in
  Fixes 1-3. Concurrent renewal extensions and transaction rollback are covered
  by Fix 4's PostgreSQL regressions.
  Keep the 16-test Tact subscription baseline as a regression check.
