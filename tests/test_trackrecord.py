"""
tests/test_trackrecord.py — SPEC-001 Phase 2 verification.

Runnable two ways:
    pytest tests/test_trackrecord.py -v
    python tests/test_trackrecord.py

Spec acceptance criteria P2:
  * /trackrecord renders with ZERO outcomes (graceful cold start)
  * renders with mixed data
  * stated denominators always sum
  * misses list links real receipt ids
Plus: /proof lookup (verdict, outcome, hash prefix, not-found, too-short),
and render_proof honesty (anchoring explicitly pending).
"""

import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import outcome_tracker as ot            # noqa: E402
from handlers.trackrecord import render_proof, render_trackrecord  # noqa: E402

T0 = 1_800_000_000.0
H, D = 3600, 86400


def _verdict(vid, addr, risk, liq0, px0):
    return {"verdict_id": vid, "address": addr, "symbol": vid, "name": vid,
            "risk_level": risk, "checked_at": T0,
            "liquidity_usd": liq0, "price_usd": px0, "volume_24h": 1000.0,
            "flags": [], "source": "test"}


DEAD = {"ok": True, "liquidity_usd": 20, "price_usd": 0.001, "volume_24h": 0}
LIVE = {"ok": True, "liquidity_usd": 50_000, "price_usd": 1.0, "volume_24h": 9_000}


async def _graded_env(tmp):
    """Build a small graded ledger: RUG (high, dies), MISS (low, dies), OK (low, lives)."""
    ot.LEDGER_FILE = os.path.join(tmp, "verdicts.jsonl")
    ot.DB_FILE = os.path.join(tmp, "receipts.db")
    verdicts = [_verdict("aaaa11112222", "EQr", "high", 50_000, 1.0),
                _verdict("bbbb11112222", "EQm", "low", 50_000, 1.0),
                _verdict("cccc11112222", "EQo", "low", 50_000, 1.0)]
    with open(ot.LEDGER_FILE, "w", encoding="utf-8") as f:
        for v in verdicts:
            v["verdict_hash"] = ot.canonical_hash(v)
            f.write(json.dumps(v) + "\n")
    box = {"now": T0}
    ot.set_clock(lambda: box["now"])

    async def fetch(q):
        return LIVE if q == "EQo" else DEAD
    ot.set_market_fetcher(fetch)
    for e in (24 * H + 60, 72 * H + 60, 7 * D + 60, 30 * D + 60):
        box["now"] = T0 + e
        await ot.evaluate_once()
    return verdicts


# --------------------------------------------------------------------------- #
# render_trackrecord
# --------------------------------------------------------------------------- #
def test_cold_start_no_verdicts():
    txt = render_trackrecord({}, {}, {"total": 0})
    assert "No verdicts recorded yet" in txt
    assert "anchoring" in txt.lower()
    print("✓ cold start (no verdicts): graceful, no fake numbers")


def test_cold_start_ungraded():
    txt = render_trackrecord({"finalized": 0}, {"total": 12, "finalized": 0},
                             {"total": 12, "high": 3, "medium": 4, "low": 4, "unknown": 1})
    assert "12" in txt and "Grading in progress" in txt
    assert "recall" not in txt.lower()          # no rates invented before data exists
    print("✓ issued-but-ungraded: shows counts + maturity note, no invented rates")


async def test_graded_render_denominators_and_misses():
    with tempfile.TemporaryDirectory() as tmp:
        await _graded_env(tmp)
        st = await ot.track_record_stats()
        pending = await ot.pending_counts()
        txt = render_trackrecord(st, pending, {"total": 3})

        # denominators must sum: graded == sum(labels)
        assert st["finalized"] == sum(st["labels"].values())
        # recall fraction appears verbatim with its denominator
        r = st["recall"]
        assert f"{r['flagged']} of {r['dead_total']}" in txt
        # calibration bucket entries expose dead/total pairs that sum correctly
        for lvl, b in st["calibration"].items():
            assert f"({b['dead']}/{b['total']})" in txt
        cal_total = sum(b["total"] for b in st["calibration"].values())
        assert cal_total == st["finalized"] - sum(st["excluded"].values())
        # the miss (low-rated token that died) is linked by its real receipt id
        assert "bbbb11112222" in txt
        # false-alarm line present with denominator
        fa = st["false_alarm_rate"]
        assert f"{fa['alive_high']} of {fa['high_total']}" in txt
    print("✓ graded card: denominators sum, miss linked by real receipt id")


# --------------------------------------------------------------------------- #
# /proof — lookup + render
# --------------------------------------------------------------------------- #
async def test_proof_lookup_paths():
    with tempfile.TemporaryDirectory() as tmp:
        verdicts = await _graded_env(tmp)

        # by verdict_id (exact)
        hit = await ot.lookup_receipt("aaaa11112222")
        assert hit and hit["kind"] == "verdict" and hit["final_label"] == "rugged"

        # by hash prefix (first 12 chars)
        h = verdicts[1]["verdict_hash"]
        hit2 = await ot.lookup_receipt(h[:12])
        assert hit2 and hit2["record"]["verdict_id"] == "bbbb11112222"

        # outcome records are findable via their own hash
        with open(ot.LEDGER_FILE, encoding="utf-8") as f:
            orecs = [json.loads(l) for l in f if '"type": "outcome"' in l or '"type":"outcome"' in l]
        assert orecs, "graded env must have outcome records"
        hit3 = await ot.lookup_receipt(orecs[0]["outcome_hash"][:16])
        assert hit3 and hit3["kind"] == "outcome"

        # F1: receipt-id PREFIX (>=8 chars) also resolves
        hit4 = await ot.lookup_receipt("aaaa1111")
        assert hit4 and hit4["record"]["verdict_id"] == "aaaa11112222"

        # not found + too-short + non-hex are safe
        assert await ot.lookup_receipt("ffffffffffff") is None
        assert await ot.lookup_receipt("abc") is None
        assert await ot.lookup_receipt("../etc/passwd") is None

        # F2: every real (non-skipped) outcome snapshot records the verdict age
        import sqlite3
        conn = sqlite3.connect(ot.DB_FILE)
        try:
            for (sig,) in conn.execute(
                    "SELECT signals FROM outcomes WHERE label != 'skipped'").fetchall():
                assert json.loads(sig).get("age_days") is not None
        finally:
            conn.close()
    print("✓ /proof lookup: id, id-prefix, hash prefix, outcome hash, hostile input, age_days")


async def test_proof_render_honesty():
    with tempfile.TemporaryDirectory() as tmp:
        await _graded_env(tmp)
        hit = await ot.lookup_receipt("aaaa11112222")
        txt = render_proof(hit, "aaaa11112222")
        assert "rugged" in txt
        assert hit["record"]["verdict_hash"] in txt        # full hash shown
        assert "pending" in txt.lower()                    # anchoring never overclaimed
        assert "sha-256" in txt.lower()
        nf = render_proof(None, "deadbeef4242")
        assert "No receipt found" in nf
    print("✓ /proof render: full hash, graded outcome, anchoring honestly pending")


def test_html_safety():
    """Hostile input can't smuggle HTML: queries are capped AND escaped, and
    token symbols (deployer-controlled DEX metadata!) are escaped in renders."""
    nf = render_proof(None, "a" * 500)
    q = re.search(r"<code>(.*?)</code>", nf).group(1)
    assert len(q) <= 64
    evil = render_proof(None, '<b onmouseover="x">y')
    assert "<b onmouseover" not in evil and "&lt;b" in evil
    # symbol injection through the misses list
    st = {"finalized": 1, "labels": {"rugged": 1},
          "recall": {"flagged": 0, "dead_total": 1, "pct": 0.0},
          "false_alarm_rate": None, "excluded": {},
          "misses": [{"verdict_id": "abcd12345678", "symbol": "<i>EVIL</i>",
                      "risk_level": "low", "label": "rugged"}],
          "calibration": {"low": {"dead": 1, "total": 1, "death_rate_pct": 100.0}}}
    card = render_trackrecord(st, {"total": 1, "maturing": 0}, {"total": 1})
    assert "<i>EVIL</i>" not in card and "&lt;i&gt;EVIL&lt;/i&gt;" in card
    print("✓ hostile queries and deployer-controlled symbols are HTML-escaped")


ALL_ASYNC = [test_graded_render_denominators_and_misses,
             test_proof_lookup_paths, test_proof_render_honesty]


async def _run_all():
    test_cold_start_no_verdicts()
    test_cold_start_ungraded()
    test_html_safety()
    for t in ALL_ASYNC:
        ot.set_clock(None)
        ot.set_market_fetcher(None)
        await t()
    ot.set_clock(None)
    ot.set_market_fetcher(None)
    print("\nAll track-record tests passed ✅")


def test_all_pytest():
    asyncio.run(_run_all())


if __name__ == "__main__":
    asyncio.run(_run_all())
