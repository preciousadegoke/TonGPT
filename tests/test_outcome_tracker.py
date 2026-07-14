"""
tests/test_outcome_tracker.py — SPEC-001 Phase 1 verification.

Runnable two ways:
    pytest tests/test_outcome_tracker.py -v
    python tests/test_outcome_tracker.py

Fixture-driven archetypes (spec acceptance criteria P1):
  RUG    fast rug (liq pulled)            — high risk   → rugged (early confirm)
  DIP    dip-then-recovery                — medium risk → alive (recovery guard)
  SLOW   slow collapse (liq not pulled)   — low risk    → collapsed (a MISS)
  OK     healthy                          — low risk    → alive
  FA     high-risk call that stayed alive — high risk   → alive (false alarm)
  MICRO  dust-liquidity token             — high risk   → rugged but EXCLUDED
  GAP    market data never available      — medium risk → indeterminate, excluded

Plus: idempotent re-run, downtime catch-up (skipped horizons can't fake a
sustained-72h confirmation), backpressure cap, canonical hash stability.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import outcome_tracker as ot  # noqa: E402

T0 = 1_800_000_000.0
H = 3600
D = 86400


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _verdict(vid, addr, risk, liq0, px0):
    return {"verdict_id": vid, "address": addr, "symbol": vid, "name": vid,
            "risk_level": risk, "checked_at": T0,
            "liquidity_usd": liq0, "price_usd": px0, "volume_24h": 1000.0,
            "flags": [], "source": "test"}


VERDICTS = [
    _verdict("RUG", "EQrug", "high", 50_000, 1.0),
    _verdict("DIP", "EQdip", "medium", 50_000, 1.0),
    _verdict("SLOW", "EQslow", "low", 5_000, 1.0),
    _verdict("OK", "EQok", "low", 80_000, 2.0),
    _verdict("FA", "EQfa", "high", 20_000, 0.5),
    _verdict("MICRO", "EQmicro", "high", 300, 0.001),
    _verdict("GAP", "EQgap", "medium", 10_000, 1.0),
]

HEALTHY = {
    "EQrug": {"ok": True, "liquidity_usd": 50_000, "price_usd": 1.0, "volume_24h": 10_000},
    "EQdip": {"ok": True, "liquidity_usd": 45_000, "price_usd": 0.9, "volume_24h": 8_000},
    "EQslow": {"ok": True, "liquidity_usd": 5_000, "price_usd": 1.0, "volume_24h": 900},
    "EQok": {"ok": True, "liquidity_usd": 90_000, "price_usd": 2.2, "volume_24h": 30_000},
    "EQfa": {"ok": True, "liquidity_usd": 22_000, "price_usd": 0.6, "volume_24h": 4_000},
}
DEAD_RUG = {"ok": True, "liquidity_usd": 20, "price_usd": 0.001, "volume_24h": 0}
DEAD_SLOW = {"ok": True, "liquidity_usd": 3_000, "price_usd": 0.04, "volume_24h": 2}
DEAD_MICRO = {"ok": True, "liquidity_usd": 1, "price_usd": 0.000001, "volume_24h": 0}


def _market_at(addr, elapsed):
    """Scripted market history per archetype, as a function of time since verdict."""
    if addr == "EQgap":
        return None                                  # data never available
    if addr == "EQrug":
        return HEALTHY[addr] if elapsed < 48 * H else DEAD_RUG
    if addr == "EQdip":
        # dead-looking ONLY around the 72h snapshot, recovered by 7d
        if 48 * H <= elapsed < 5 * D:
            return {"ok": True, "liquidity_usd": 1_500, "price_usd": 0.02, "volume_24h": 0}
        return HEALTHY[addr]
    if addr == "EQslow":
        return HEALTHY[addr] if elapsed < 12 * H else DEAD_SLOW
    if addr == "EQmicro":
        return DEAD_MICRO if elapsed >= 48 * H else {"ok": True, "liquidity_usd": 300,
                                                     "price_usd": 0.001, "volume_24h": 50}
    return HEALTHY[addr]                             # EQok, EQfa stay healthy


# --------------------------------------------------------------------------- #
# Harness
# --------------------------------------------------------------------------- #
class Env:
    """Fresh ledger+db in a tempdir, scripted clock and market fetcher."""

    def __init__(self, tmp, verdicts):
        self.now = T0
        ot.LEDGER_FILE = os.path.join(tmp, "verdicts.jsonl")
        ot.DB_FILE = os.path.join(tmp, "receipts.db")
        with open(ot.LEDGER_FILE, "w", encoding="utf-8") as f:
            for v in verdicts:
                f.write(json.dumps(v) + "\n")
        ot.set_clock(lambda: self.now)

        async def fetch(query):
            return _market_at(query, self.now - T0)
        ot.set_market_fetcher(fetch)

    async def run_at(self, elapsed):
        self.now = T0 + elapsed
        return await ot.evaluate_once()

    def finals(self):
        import sqlite3
        conn = sqlite3.connect(ot.DB_FILE)
        try:
            return dict(conn.execute(
                "SELECT verdict_id, final_label FROM verdicts").fetchall())
        finally:
            conn.close()

    def outcome_rows(self):
        import sqlite3
        conn = sqlite3.connect(ot.DB_FILE)
        try:
            return conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
async def test_archetype_labels():
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp, VERDICTS)
        for elapsed in (24 * H + 60, 72 * H + 60, 7 * D + 60, 30 * D + 60):
            await env.run_at(elapsed)
        finals = env.finals()
        assert finals["RUG"] == "rugged", finals
        assert finals["DIP"] == "alive", finals          # recovery guard held
        assert finals["SLOW"] == "collapsed", finals
        assert finals["OK"] == "alive", finals
        assert finals["FA"] == "alive", finals
        assert finals["MICRO"] == "rugged", finals
        assert finals["GAP"] == "indeterminate", finals
    print("✓ all 7 archetypes get the expected final label (dip is NOT a rug)")


async def test_early_confirmation_and_idempotency():
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp, VERDICTS)
        await env.run_at(24 * H + 60)
        await env.run_at(72 * H + 60)
        s3 = await env.run_at(7 * D + 60)
        # RUG dead at 72h AND 7d -> finalized at the 7d pass, before 30d.
        assert env.finals()["RUG"] == "rugged"
        assert s3["finalized"] >= 1
        # Re-running at the same instant must change nothing.
        rows_before = env.outcome_rows()
        again = await env.run_at(7 * D + 60)
        assert again["evaluated"] == 0 and again["finalized"] == 0, again
        assert env.outcome_rows() == rows_before
    print("✓ rug finalizes early on 72h+7d confirmation; re-run is a no-op")


async def test_downtime_skip_integrity():
    """Tracker down for the whole month: one real snapshot, no fake sustainment."""
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp, [_verdict("RUG2", "EQrug", "high", 50_000, 1.0)])
        s = await env.run_at(30 * D + 60)     # first pass ever, all horizons overdue
        assert s["evaluated"] == 1, s          # only the 30d horizon got real data
        finals = env.finals()
        # Dead at 30d with no counter-evidence (earlier horizons skipped) keeps
        # the dead label — a drained pool does not refill.
        assert finals["RUG2"] == "rugged", finals
    print("✓ downtime catch-up: earlier horizons skipped, single honest snapshot")


async def test_downtime_skip_live_counterevidence():
    """Dead ONLY at 30d while 7d was verifiably alive -> indeterminate."""
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp, [_verdict("LATE", "EQrug", "high", 50_000, 1.0)])
        await env.run_at(24 * H + 60)
        await env.run_at(72 * H + 60)
        env_fetch_alive_until = 20 * D        # alive at 7d, dead at 30d

        async def fetch(query):
            if env.now - T0 < env_fetch_alive_until:
                return HEALTHY["EQrug"]
            return DEAD_RUG
        ot.set_market_fetcher(fetch)
        await env.run_at(7 * D + 60)
        await env.run_at(30 * D + 60)
        finals = env.finals()
        assert finals["LATE"] == "indeterminate", finals
    print("✓ death seen only at the final snapshot is not claimed as a confirmed rug")


async def test_track_record_stats():
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp, VERDICTS)
        for elapsed in (24 * H + 60, 72 * H + 60, 7 * D + 60, 30 * D + 60):
            await env.run_at(elapsed)
        st = await ot.track_record_stats()
        assert st["finalized"] == 7, st
        # Non-excluded graded set: RUG, DIP, SLOW, OK, FA (MICRO+GAP excluded).
        assert st["excluded"] == {"microcap": 1, "indeterminate": 1}, st
        assert st["recall"] == {"flagged": 1, "dead_total": 2, "pct": 50.0}, st
        assert st["false_alarm_rate"] == {"alive_high": 1, "high_total": 2, "pct": 50.0}, st
        misses = {m["verdict_id"] for m in st["misses"]}
        assert misses == {"SLOW"}, st["misses"]
        assert st["calibration"]["high"] == {"dead": 1, "total": 2, "death_rate_pct": 50.0}
        assert st["calibration"]["low"] == {"dead": 1, "total": 2, "death_rate_pct": 50.0}
        assert st["calibration"]["medium"] == {"dead": 0, "total": 1, "death_rate_pct": 0.0}
    print("✓ stats: recall, false-alarm rate, misses, calibration — all with denominators")


def test_canonical_hash():
    a = {"x": 1, "y": [1, 2], "z": "é"}
    b = {"z": "é", "y": [1, 2], "x": 1}                       # different order
    assert ot.canonical_hash(a) == ot.canonical_hash(b)
    c = dict(a, verdict_hash="whatever", outcome_hash="w2")   # hash fields excluded
    assert ot.canonical_hash(c) == ot.canonical_hash(a)
    assert ot.canonical_hash(dict(a, x=2)) != ot.canonical_hash(a)
    print("✓ canonical hash is order-independent and excludes hash fields")


async def test_outcome_records_appended_to_ledger():
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp, VERDICTS)
        for elapsed in (24 * H + 60, 72 * H + 60, 7 * D + 60, 30 * D + 60):
            await env.run_at(elapsed)
        types = {}
        with open(ot.LEDGER_FILE, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                types[rec.get("type", "verdict")] = types.get(rec.get("type", "verdict"), 0) + 1
        assert types["verdict"] == 7 and types["outcome"] == 7, types
        # ingest must NOT re-ingest our own outcome records as verdicts
        s = await env.run_at(31 * D)
        assert s["ingested"] == 0, s
    print("✓ final outcomes are appended to the ledger and never re-ingested")


async def test_backpressure_cap():
    """Fetch cap defers evaluation to later passes without losing anything."""
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp, [_verdict("A", "EQok", "low", 80_000, 2.0),
                        _verdict("B", "EQfa", "high", 20_000, 0.5),
                        _verdict("C", "EQslow", "low", 5_000, 1.0)])
        old_cap = ot.MAX_FETCH_PER_PASS
        ot.MAX_FETCH_PER_PASS = 2
        try:
            s1 = await env.run_at(24 * H + 60)
            assert s1["evaluated"] == 2, s1          # capped
            s2 = await env.run_at(24 * H + 120)
            assert s2["evaluated"] == 1, s2          # deferred one catches up
        finally:
            ot.MAX_FETCH_PER_PASS = old_cap
    print("✓ fetch cap defers, never drops (backpressure)")


ALL = [test_archetype_labels, test_early_confirmation_and_idempotency,
       test_downtime_skip_integrity, test_downtime_skip_live_counterevidence,
       test_track_record_stats, test_outcome_records_appended_to_ledger,
       test_backpressure_cap]


async def _run_all():
    test_canonical_hash()
    for t in ALL:
        # reset injected hooks between tests
        ot.set_clock(None)
        ot.set_market_fetcher(None)
        await t()
    ot.set_clock(None)
    ot.set_market_fetcher(None)
    print("\nAll outcome tracker tests passed ✅")


def test_all_pytest():
    asyncio.run(_run_all())


if __name__ == "__main__":
    asyncio.run(_run_all())
