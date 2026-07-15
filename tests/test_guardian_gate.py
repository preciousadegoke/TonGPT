"""
tests/test_guardian_gate.py — SPEC-002 Phase 1 verification.

Runnable two ways:
    pytest tests/test_guardian_gate.py -v
    python tests/test_guardian_gate.py

Spec acceptance criteria P1:
  * advice policy matrix (high→block, medium→warn, low→pass+FN-rate,
    unknown/unindexed→block, degraded→warn)
  * every response carries a receipt (verdict id + gate receipt hash)
  * gate_check records land in the ledger, are hashed, are SKIPPED by the
    outcome tracker's verdict ingestion, and become Merkle leaves for anchoring
  * auth + per-key daily quota enforced
  * invalid/hostile addresses rejected before any lookup
  * cache serves within TTL and still receipts every check
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import guardian_gate as gg     # noqa: E402
from services import outcome_tracker as ot   # noqa: E402
from services import receipts_anchor as ra   # noqa: E402
import services.verdict as vd                # noqa: E402

T0 = 1_800_000_000.0
ADDR = "EQ" + "A" * 46          # friendly-form shaped
RAW = "0:" + "ab" * 32


def _fake_verdict(risk="high", stale=False):
    return vd.Verdict(symbol="TEST", name="Test Token", address=ADDR,
                      risk_level=risk, flags=[f"{risk} flag"],
                      liquidity_usd=9000.0, volume_24h=500.0, price_usd=0.5,
                      stale=stale, checked_at=T0)


GRADED_STATS = {
    "finalized": 40,
    "labels": {"rugged": 20, "alive": 20},
    "calibration": {"high": {"dead": 18, "total": 22, "death_rate_pct": 81.8},
                    "low": {"dead": 1, "total": 12, "death_rate_pct": 8.3}},
    "recall": {"flagged": 18, "dead_total": 21, "pct": 85.7},
    "false_alarm_rate": {"alive_high": 4, "high_total": 22, "pct": 18.2},
    "misses": [], "excluded": {"microcap": 0, "indeterminate": 0},
}


class Env:
    def __init__(self, tmp, verdict_result="high", stats=GRADED_STATS):
        gg.LEDGER_FILE = ot.LEDGER_FILE = ra.LEDGER_FILE = os.path.join(tmp, "l.jsonl")
        self._orig_vd_ledger = vd.LEDGER_FILE
        vd.LEDGER_FILE = gg.LEDGER_FILE          # fake check_token receipts land in tmp
        ot.DB_FILE = os.path.join(tmp, "r.db")
        self.now = T0
        gg.set_clock(lambda: self.now)
        gg._cache.clear()
        gg._quota.clear()
        gg._stats_cache.update(ts=0.0, stats=None)

        async def fake_check_token(q):
            if verdict_result is None:
                return None
            v = _fake_verdict(verdict_result if verdict_result != "stale-low" else "low",
                              stale=(verdict_result == "stale-low"))
            await vd._record(v)          # real ledger write, like production
            return v
        self._orig = vd.check_token
        vd.check_token = fake_check_token

        async def fake_stats():
            return stats
        self._orig_stats = gg._stats
        gg._stats = fake_stats

    def restore(self):
        vd.check_token = self._orig
        vd.LEDGER_FILE = self._orig_vd_ledger
        gg._stats = self._orig_stats
        gg.set_clock(None)

    def ledger(self):
        with open(gg.LEDGER_FILE, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]


# --------------------------------------------------------------------------- #
# Pure policy + validation
# --------------------------------------------------------------------------- #
def test_advice_policy_matrix():
    assert gg.advice_for("high", False, False) == "block"
    assert gg.advice_for("unknown", False, False) == "block"
    assert gg.advice_for("medium", False, False) == "warn"
    assert gg.advice_for("low", True, False) == "warn"        # degraded data
    assert gg.advice_for("low", False, False) == "pass"
    assert gg.advice_for("low", False, True) == "block"       # unindexed trumps all
    print("✓ advice policy matrix: block/warn/pass with fail-closed defaults")


def test_address_validation():
    assert gg.is_valid_address(ADDR)
    assert gg.is_valid_address(RAW)
    assert gg.is_valid_address("-1:" + "0" * 64)
    for bad in ("", "hello", "EQshort", "0:zz" + "0" * 62, "../etc/passwd",
                "EQ" + "A" * 46 + "; DROP TABLE", "<script>", "EQ" + "A" * 100):
        assert not gg.is_valid_address(bad), bad
    print("✓ address validation: friendly + raw accepted, hostile rejected")


# --------------------------------------------------------------------------- #
# gate_check end-to-end
# --------------------------------------------------------------------------- #
async def test_high_risk_blocks_with_receipts():
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp, "high")
        try:
            r = await gg.gate_check(ADDR, "agent-dev-1")
            assert r["advice"] == "block" and r["risk_level"] == "high"
            assert r["receipt"]["verdict_id"]
            assert r["gate_receipt"] and len(r["gate_receipt"]) == 64
            tr = r["track_record"]
            assert tr["observed_30d_death_rate"] == {"pct": 81.8, "dead": 18, "total": 22}
            assert tr["false_negative_rate"]["total"] == 12
            assert "guarantee" in r["disclaimer"] or "not guarantees" in r["disclaimer"]
            # ledger got BOTH the verdict receipt and the gate receipt
            types = [rec.get("type", "verdict") for rec in env.ledger()]
            assert types.count("gate_check") == 1 and types.count("verdict") == 1
            gate = [rec for rec in env.ledger() if rec.get("type") == "gate_check"][0]
            assert gate["gate_hash"] == ot.canonical_hash(gate)     # re-verifiable
            assert gate["caller"] != "agent-dev-1"                  # hashed, not raw
        finally:
            env.restore()
    print("✓ high risk → block; verdict + gate receipts ledgered, hash re-verifiable")


async def test_pass_carries_fn_rate_and_unindexed_blocks():
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp, "low")
        try:
            r = await gg.gate_check(ADDR, "a")
            assert r["advice"] == "pass"
            assert r["track_record"]["false_negative_rate"]["pct"] == 8.3
        finally:
            env.restore()
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp, None)                       # token not found anywhere
        try:
            r = await gg.gate_check(ADDR, "a")
            assert r["advice"] == "block" and r["unindexed"] is True
            assert r["receipt"] is None
            assert any("unindexed" in f for f in r["flags"])
            # even unindexed checks are receipted
            assert any(rec.get("type") == "gate_check" for rec in env.ledger())
        finally:
            env.restore()
    print("✓ pass ships its false-negative rate; unindexed fails closed, still receipted")


async def test_degraded_warns_and_cold_start_is_honest():
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp, "stale-low", stats=None)    # stale data + zero history
        try:
            r = await gg.gate_check(ADDR, "a")
            assert r["advice"] == "warn" and r["degraded"] is True
            tr = r["track_record"]
            assert tr["insufficient_history"] is True
            assert tr["observed_30d_death_rate"] is None       # nothing invented
        finally:
            env.restore()
    print("✓ degraded data → warn; cold-start history is honestly insufficient")


async def test_cache_and_every_check_receipted():
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp, "medium")
        try:
            r1 = await gg.gate_check(ADDR, "a")
            r2 = await gg.gate_check(ADDR, "b")
            assert r1["cached"] is False and r2["cached"] is True
            gates = [rec for rec in env.ledger() if rec.get("type") == "gate_check"]
            assert len(gates) == 2                              # both receipted
            assert gates[0]["caller"] != gates[1]["caller"]
            env.now += gg.CACHE_TTL + 1
            r3 = await gg.gate_check(ADDR, "a")
            assert r3["cached"] is False                        # TTL expired
        finally:
            env.restore()
    print("✓ 60s cache serves repeats; every check still becomes a receipt")


async def test_pipeline_integration():
    """Gate records must NOT be ingested as verdicts, but MUST be Merkle leaves."""
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp, "high")
        try:
            await gg.gate_check(ADDR, "a")
            ot.set_clock(lambda: env.now)

            async def no_fetch(q):
                return None
            ot.set_market_fetcher(no_fetch)
            s = await ot.evaluate_once()
            assert s["ingested"] == 1        # ONLY the verdict, not the gate record

            gate = [r for r in env.ledger() if r.get("type") == "gate_check"][0]
            lt = ra._record_leaf_and_ts(gate)
            assert lt is not None and lt[0] == gate["gate_hash"]
        finally:
            env.restore()
            ot.set_clock(None)
            ot.set_market_fetcher(None)
    print("✓ pipelines: tracker skips gate records, anchor treats them as leaves")


def test_auth_and_quota():
    os.environ["GUARDIAN_API_KEYS"] = "alice:0123456789abcdef,bob:tooshort,carl:fedcba9876543210"
    try:
        assert gg.authenticate("0123456789abcdef") == "alice"
        assert gg.authenticate("fedcba9876543210") == "carl"
        assert gg.authenticate("tooshort") is None              # <16 chars rejected
        assert gg.authenticate("wrong") is None
        assert gg.authenticate(None) is None

        gg._quota.clear()
        old = gg.FREE_CHECKS_PER_DAY
        gg.FREE_CHECKS_PER_DAY = 2
        box = {"now": T0}
        gg.set_clock(lambda: box["now"])
        try:
            assert gg.consume_quota("alice") and gg.consume_quota("alice")
            assert not gg.consume_quota("alice")                # exhausted
            assert gg.consume_quota("carl")                     # independent keys
            box["now"] += 86400
            assert gg.consume_quota("alice")                    # daily rollover
        finally:
            gg.FREE_CHECKS_PER_DAY = old
            gg.set_clock(None)
    finally:
        del os.environ["GUARDIAN_API_KEYS"]
    print("✓ auth: keyring parsing, short-key rejection; quota: cap + rollover")


async def test_invalid_address_short_circuits():
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp, "high")
        try:
            r = await gg.gate_check("<script>alert(1)</script>", "a")
            assert r["error"] == "invalid_address"
            assert not os.path.exists(gg.LEDGER_FILE) or not env.ledger()
        finally:
            env.restore()
    print("✓ invalid address rejected before any lookup or ledger write")


ALL_ASYNC = [test_high_risk_blocks_with_receipts,
             test_pass_carries_fn_rate_and_unindexed_blocks,
             test_degraded_warns_and_cold_start_is_honest,
             test_cache_and_every_check_receipted,
             test_pipeline_integration,
             test_invalid_address_short_circuits]


async def _run_all():
    test_advice_policy_matrix()
    test_address_validation()
    test_auth_and_quota()
    for t in ALL_ASYNC:
        await t()
    print("\nAll guardian-gate tests passed ✅")


def test_all_pytest():
    asyncio.run(_run_all())


if __name__ == "__main__":
    asyncio.run(_run_all())
