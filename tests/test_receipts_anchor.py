"""
tests/test_receipts_anchor.py — SPEC-001 Phase 3 (off-chain half) verification.

Runnable two ways:
    pytest tests/test_receipts_anchor.py -v
    python tests/test_receipts_anchor.py

Covers:
  * Merkle engine: determinism, order-independence, proof verification for
    EVERY leaf, tamper rejection, single-leaf and odd-count trees
  * day partitioning + anchor_once(): computes roots for completed days only,
    idempotent, skips empty days, respects the backfill window
  * mark_anchored() records the operator tx exactly once
  * get_anchor_info(): serves a verifying inclusion proof for a real receipt
  * /proof render integration: pending → computed → anchored states

(The on-chain half — anchor_registry.tolk — is verified against real TVM
bytecode by scripts/verify_anchor_contract.js and tests/AnchorRegistry.spec.ts.)
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import outcome_tracker as ot     # noqa: E402
from services import receipts_anchor as ra     # noqa: E402
from handlers.trackrecord import render_proof  # noqa: E402

D = 86400
DAY0 = 20_650                                   # a fixed UTC day index
T_DAY0 = DAY0 * D + 3600                        # 01:00 UTC that day


def _mk_hash(i: int) -> str:
    import hashlib
    return hashlib.sha256(f"leaf-{i}".encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Merkle engine
# --------------------------------------------------------------------------- #
def test_merkle_properties():
    leaves = [_mk_hash(i) for i in range(7)]                  # odd count
    root = ra.merkle_root(leaves)
    assert root == ra.merkle_root(list(reversed(leaves)))     # order-independent
    assert root != ra.merkle_root(leaves[:6])
    for leaf in leaves:                                       # every proof verifies
        proof = ra.merkle_proof(leaves, leaf)
        assert proof is not None
        assert ra.verify_proof(leaf, proof, root), leaf
        assert not ra.verify_proof(_mk_hash(99), proof, root)  # wrong leaf fails
    # tampered sibling fails
    proof = ra.merkle_proof(leaves, leaves[0])
    if proof:
        bad = [("0" * 64 if i == 0 else p) for i, p in enumerate(proof)]
        assert not ra.verify_proof(leaves[0], bad, root)
    # single leaf: root == leaf, empty proof verifies
    single = ra.merkle_root([leaves[0]])
    assert single == leaves[0]
    assert ra.merkle_proof([leaves[0]], leaves[0]) == []
    assert ra.verify_proof(leaves[0], [], single)
    # empty set
    assert ra.merkle_root([]) is None
    # duplicates collapse deterministically
    assert ra.merkle_root([leaves[0], leaves[0]]) == leaves[0]
    print("✓ merkle: deterministic, order-independent, proofs verify, tamper fails")


# --------------------------------------------------------------------------- #
# Harness for ledger-backed tests
# --------------------------------------------------------------------------- #
def _env(tmp, records, now):
    ot.LEDGER_FILE = os.path.join(tmp, "verdicts.jsonl")
    ot.DB_FILE = os.path.join(tmp, "receipts.db")
    ra.LEDGER_FILE = ot.LEDGER_FILE
    ra.DB_FILE = ot.DB_FILE
    with open(ot.LEDGER_FILE, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    ra.set_clock(lambda: now)


def _verdict_rec(i, ts):
    rec = {"verdict_id": f"{i:012x}", "address": f"EQ{i}", "symbol": f"T{i}",
           "risk_level": "high", "checked_at": ts, "liquidity_usd": 10_000.0,
           "price_usd": 1.0}
    rec["verdict_hash"] = ot.canonical_hash(rec)
    return rec


async def test_anchor_once_and_idempotency():
    with tempfile.TemporaryDirectory() as tmp:
        # 3 receipts on DAY0, 2 on DAY0+1, none on DAY0+2; "now" is DAY0+3
        recs = [_verdict_rec(i, T_DAY0 + i) for i in range(3)]
        recs += [_verdict_rec(10 + i, T_DAY0 + D + i) for i in range(2)]
        _env(tmp, recs, now=(DAY0 + 3) * D + 60)

        s1 = await ra.anchor_once()
        assert s1["computed"] == 2, s1                 # both completed days
        s2 = await ra.anchor_once()
        assert s2["computed"] == 0 and s2["skipped_existing"] == 2, s2

        # anchor records landed in the ledger, one per day
        with open(ra.LEDGER_FILE, encoding="utf-8") as f:
            anchors = [json.loads(l) for l in f if '"type": "anchor"' in l]
        assert len(anchors) == 2
        assert {a["day_index"] for a in anchors} == {DAY0, DAY0 + 1}
        assert all(a["count"] > 0 and len(a["merkle_root"]) == 64 for a in anchors)
    print("✓ anchor_once: completed days only, idempotent, ledger records written")


async def test_today_never_anchored_and_backfill_window():
    with tempfile.TemporaryDirectory() as tmp:
        recs = [_verdict_rec(1, T_DAY0)]                       # very old receipt
        recs += [_verdict_rec(2, (DAY0 + 100) * D + 50)]       # today's receipt
        _env(tmp, recs, now=(DAY0 + 100) * D + 3600)
        s = await ra.anchor_once()
        # old day outside 30d backfill window: skipped; today: not complete yet
        assert s["computed"] == 0, s
    print("✓ today is never anchored; backfill window respected")


async def test_mark_anchored_once():
    with tempfile.TemporaryDirectory() as tmp:
        _env(tmp, [_verdict_rec(1, T_DAY0)], now=(DAY0 + 2) * D)
        await ra.anchor_once()
        assert await ra.mark_anchored(DAY0, "txhash123") is True
        assert await ra.mark_anchored(DAY0, "txhash456") is False   # already set
        assert await ra.mark_anchored(DAY0 + 5, "tx") is False      # unknown day
    print("✓ mark_anchored records the operator tx exactly once")


async def test_get_anchor_info_serves_verifying_proof():
    with tempfile.TemporaryDirectory() as tmp:
        recs = [_verdict_rec(i, T_DAY0 + i) for i in range(5)]
        _env(tmp, recs, now=(DAY0 + 2) * D)
        await ra.anchor_once()

        target = recs[2]["verdict_hash"]
        info = await ra.get_anchor_info(target)
        assert info and info["day_index"] == DAY0 and info["count"] == 5
        assert info["verified"] is True
        assert ra.verify_proof(target, info["proof"], info["root"])

        # a hash from an un-anchored day reports pending
        recs2 = _verdict_rec(50, (DAY0 + 1) * D + 10)
        with open(ra.LEDGER_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(recs2) + "\n")
        ra.set_clock(lambda: (DAY0 + 1) * D + 20)     # that day not complete yet
        pend = await ra.get_anchor_info(recs2["verdict_hash"])
        assert pend and pend.get("status") == "pending"

        # unknown hash → None
        assert await ra.get_anchor_info("ab" * 32) is None
    print("✓ get_anchor_info: verifying proof for anchored, pending for new, None for unknown")


async def test_proof_render_three_states():
    with tempfile.TemporaryDirectory() as tmp:
        recs = [_verdict_rec(i, T_DAY0 + i) for i in range(3)]
        _env(tmp, recs, now=(DAY0 + 2) * D)
        hit = {"kind": "verdict", "record": recs[0], "final_label": None}

        # state 1: nothing computed yet
        txt1 = render_proof(hit, recs[0]["verdict_id"], None)
        assert "pending" in txt1.lower() and "root:" not in txt1.lower()

        # state 2: root computed, no tx
        await ra.anchor_once()
        info = await ra.get_anchor_info(recs[0]["verdict_hash"])
        txt2 = render_proof(hit, recs[0]["verdict_id"], info)
        assert info["root"] in txt2
        assert "awaiting the operator" in txt2
        assert "proof verifies" in txt2

        # state 3: anchored on-chain
        await ra.mark_anchored(DAY0, "abcdef_tx")
        info3 = await ra.get_anchor_info(recs[0]["verdict_hash"])
        txt3 = render_proof(hit, recs[0]["verdict_id"], info3)
        assert "abcdef_tx" in txt3 and "awaiting" not in txt3
    print("✓ /proof renders all three anchor states honestly")


ALL_ASYNC = [test_anchor_once_and_idempotency,
             test_today_never_anchored_and_backfill_window,
             test_mark_anchored_once,
             test_get_anchor_info_serves_verifying_proof,
             test_proof_render_three_states]


async def _run_all():
    test_merkle_properties()
    for t in ALL_ASYNC:
        ra.set_clock(None)
        await t()
    ra.set_clock(None)
    print("\nAll receipts-anchor tests passed ✅")


def test_all_pytest():
    asyncio.run(_run_all())


if __name__ == "__main__":
    asyncio.run(_run_all())
