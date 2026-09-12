# Payment controller integration regressions

From the repository root, run:

```powershell
.\.venv\Scripts\python.exe scripts/test_payment_controller.py
```

Requires .NET 8, Docker, and the local `postgres:15-alpine` image. The runner
creates a separate PostgreSQL container on a random localhost port, uses a fresh
test database, and removes its own container afterward. It never reads `.env`,
connects to the application database, or runs a payment-identifier migration.

The executable C# suite references the real Engine project and uses its existing
EF/Npgsql dependencies. A nonzero exit code means a regression failed. It covers:

- Two concurrent notifications for the same payment: one activation, one duplicate,
  the same persisted payment ID, and one activation audit record.
- Different payments racing to create the same user: the loser returns HTTP 503,
  retry persists the second payment, and subsequent replays add no activation.
- A general `DbUpdateException` without a payment: retryable failure with no partial
  write, followed by successful, idempotent recovery.
- Concurrent TON and Stars renewals with different durations: both durations are
  added for future, expired, and null expiry; replays add no further time.
- Duplicate renewal of an existing user: only one extension and audit record.
- Failure injected after the database expiry update, before commit: payment,
  audit, plan and expiry roll back together; retry extends exactly once.

The concurrency barrier holds both requests immediately before `SaveChangesAsync`
so both read the original user state. PostgreSQL produces real uniqueness conflicts
and serializes the renewal updates. All eight cases use the actual controller.
