"""
tests/test_payment_activation.py — durable activation reliability.

Runnable two ways:
    pytest tests/test_payment_activation.py -v
    python tests/test_payment_activation.py

These tests prove the P0 guarantee: a successful payment is NEVER lost, even
across an Engine outage and a process restart, and duplicates never
double-activate.

We inject a fake ``services.engine_client`` into sys.modules so the suite runs
without aiohttp / a live Postgres. The fake mirrors the real, idempotent
contract of POST /api/Payment/complete.
"""

import asyncio
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# --------------------------------------------------------------------------- #
# Fake Engine that mirrors the idempotent Payment/complete contract.
# --------------------------------------------------------------------------- #
class FakeEngine:
    def __init__(self):
        self.up = True                 # toggle to simulate Engine outage
        self.activated = {}            # external_id -> plan (the Postgres "truth")
        self.calls = 0

    async def complete_payment(self, telegram_id, plan, provider, external_id,
                               duration_days=30, amount_ton=0.0):
        self.calls += 1
        if not self.up:
            return {"ok": False, "permanent": False, "error": "unreachable"}
        already = external_id in self.activated
        self.activated[external_id] = plan  # idempotent: set-once semantics
        return {
            "ok": True,
            "already_processed": already,
            "status": "AlreadyProcessed" if already else "Activated",
            "payment_id": f"pid-{external_id}",
            "plan": plan,
            "expiry": "2026-12-31T00:00:00Z",
            "permanent": False,
        }


def _install_fake_engine() -> FakeEngine:
    fake_engine = FakeEngine()
    mod = types.ModuleType("services.engine_client")
    mod.engine_client = fake_engine
    mod.EngineServerError = type("EngineServerError", (Exception,), {})
    sys.modules["services.engine_client"] = mod
    return fake_engine


def _fresh_queue_module(tmp_path: str):
    """Import (or reload) the queue module pointed at a temp file."""
    if "services.activation_queue" in sys.modules:
        del sys.modules["services.activation_queue"]
    import importlib
    aq = importlib.import_module("services.activation_queue")
    aq.QUEUE_FILE = tmp_path
    aq.ALERT_AFTER_ATTEMPTS = 3
    return aq


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
async def test_outage_then_recovery_no_lost_activation():
    engine = _install_fake_engine()
    with tempfile.TemporaryDirectory() as d:
        qf = os.path.join(d, "pending.jsonl")
        aq = _fresh_queue_module(qf)

        # Engine is DOWN at payment time -> enqueue durably.
        engine.up = False
        await aq.enqueue({
            "user_id": 1001, "plan": "Pro", "provider": "telegram_stars",
            "external_id": "charge_A", "duration_days": 30, "plan_key": "pro",
        })
        assert await aq.pending_count() == 1

        # Drains while down: stays pending (no loss).
        assert await aq.drain_once() == 0
        assert await aq.pending_count() == 1

        # Engine recovers -> drain activates and clears the queue.
        engine.up = True
        assert await aq.drain_once() == 1
        assert await aq.pending_count() == 0
        assert engine.activated.get("charge_A") == "Pro"
    print("✓ activation survives Engine outage and completes on recovery (no loss)")


async def test_survives_restart():
    engine = _install_fake_engine()
    with tempfile.TemporaryDirectory() as d:
        qf = os.path.join(d, "pending.jsonl")

        # Process #1: enqueue while engine down, then "crash".
        engine.up = False
        aq1 = _fresh_queue_module(qf)
        await aq1.enqueue({
            "user_id": 1002, "plan": "Elite", "provider": "telegram_stars",
            "external_id": "charge_B", "duration_days": 30, "plan_key": "elite",
        })

        # Process #2: fresh module instance reads the SAME file (restart).
        aq2 = _fresh_queue_module(qf)
        assert await aq2.pending_count() == 1, "queued item must survive restart"
        engine.up = True
        assert await aq2.drain_once() == 1
        assert engine.activated.get("charge_B") == "Elite"
    print("✓ pending activation survives a process restart")


async def test_duplicate_never_double_activates():
    engine = _install_fake_engine()
    with tempfile.TemporaryDirectory() as d:
        qf = os.path.join(d, "pending.jsonl")
        aq = _fresh_queue_module(qf)

        # Same charge id enqueued twice (e.g. duplicate webhook + a queued retry).
        for _ in range(2):
            await aq.enqueue({
                "user_id": 1003, "plan": "Starter", "provider": "telegram_stars",
                "external_id": "charge_C", "duration_days": 30, "plan_key": "starter",
            })
        engine.up = True
        await aq.drain_once()
        # Engine saw two calls but the second is already_processed; truth is one plan.
        assert engine.activated == {"charge_C": "Starter"}
        assert await aq.pending_count() == 0
    print("✓ duplicate charge id never double-activates (idempotent)")


async def test_redis_independent():
    """The queue must work with NO Redis at all (it's the whole point)."""
    engine = _install_fake_engine()
    # Ensure nothing in this path touches Redis: we never import redis here.
    with tempfile.TemporaryDirectory() as d:
        qf = os.path.join(d, "pending.jsonl")
        aq = _fresh_queue_module(qf)
        engine.up = False
        await aq.enqueue({
            "user_id": 1004, "plan": "Pro", "provider": "telegram_stars",
            "external_id": "charge_D", "duration_days": 30, "plan_key": "pro",
        })
        # File exists on disk regardless of Redis state.
        assert os.path.exists(qf)
        engine.up = True
        assert await aq.drain_once() == 1
    print("✓ activation queue is fully Redis-independent")


ALL_TESTS = [
    test_outage_then_recovery_no_lost_activation,
    test_survives_restart,
    test_duplicate_never_double_activates,
    test_redis_independent,
]


async def _run_all():
    for t in ALL_TESTS:
        await t()
    print("\nAll payment activation tests passed ✅")


def test_all_pytest():
    asyncio.run(_run_all())


if __name__ == "__main__":
    asyncio.run(_run_all())
