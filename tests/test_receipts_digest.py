"""
tests/test_receipts_digest.py — SPEC-001 Phase 4 verification.

Runnable two ways:
    pytest tests/test_receipts_digest.py -v
    python tests/test_receipts_digest.py

Covers: never posts before data exists, honest graded render (denominators,
misses count, anchor status), weekly dedup via the meta table, channel gating.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import outcome_tracker as ot      # noqa: E402
from services import receipts_anchor as ra      # noqa: E402
from services import receipts_digest as rd      # noqa: E402

D = 86400
DAY0 = 20_650
T_DAY0 = DAY0 * D + 3600


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat, text, **kw):
        self.sent.append((chat, text))

    async def me(self):
        class _Me:
            username = "TonGPT_Test_Bot"
        return _Me()


def _verdict_rec(i, risk, ts):
    rec = {"verdict_id": f"{i:012x}", "address": f"EQ{i}", "symbol": f"T{i}",
           "risk_level": risk, "checked_at": ts, "liquidity_usd": 10_000.0,
           "price_usd": 1.0}
    rec["verdict_hash"] = ot.canonical_hash(rec)
    return rec


async def _graded_env(tmp, now):
    ot.LEDGER_FILE = os.path.join(tmp, "verdicts.jsonl")
    ot.DB_FILE = os.path.join(tmp, "receipts.db")
    ra.LEDGER_FILE = ot.LEDGER_FILE
    recs = [_verdict_rec(1, "high", T_DAY0), _verdict_rec(2, "low", T_DAY0 + 5)]
    with open(ot.LEDGER_FILE, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    box = {"now": T_DAY0}
    ot.set_clock(lambda: box["now"])
    rd.set_clock(lambda: box["now"])
    ra.set_clock(lambda: box["now"])

    async def fetch(q):
        if q == "EQ1":
            return {"ok": True, "liquidity_usd": 10, "price_usd": 0.001, "volume_24h": 0}
        return {"ok": True, "liquidity_usd": 20_000, "price_usd": 1.1, "volume_24h": 900}
    ot.set_market_fetcher(fetch)
    for e in (24 * 3600 + 60, 72 * 3600 + 60, 7 * D + 60, 30 * D + 60):
        box["now"] = T_DAY0 + e
        await ot.evaluate_once()
    await ra.anchor_once()
    return box


def test_no_post_before_data():
    assert rd.render_digest({}, 0, {}) is None
    assert rd.render_digest({"finalized": 0}, 0, {}) is None
    print("✓ digest never renders before any verdict is graded")


async def test_graded_digest_render_and_dedup():
    with tempfile.TemporaryDirectory() as tmp:
        box = await _graded_env(tmp, None)
        os.environ["RADAR_CHANNEL_ID"] = "@test_channel"
        try:
            bot = FakeBot()
            posted = await rd.digest_once(bot)
            assert posted is True and len(bot.sent) == 1
            chan, text = bot.sent[0]
            assert chan == "@test_channel"
            # honesty markers
            assert "weekly digest" in text
            assert "Misses" in text or "Misses on record" in text
            assert "of" in text                      # denominators phrasing
            assert "Merkle roots" in text            # anchor status included
            assert "@TonGPT_Test_Bot" in text
            # dedup: immediate second call must NOT post
            assert await rd.digest_once(bot) is False
            assert len(bot.sent) == 1
            # a week later it posts again
            box["now"] += 8 * D
            assert await rd.digest_once(bot) is True
            assert len(bot.sent) == 2
        finally:
            del os.environ["RADAR_CHANNEL_ID"]
    print("✓ digest posts honest content once per interval, dedups across calls")


async def test_channel_gating():
    with tempfile.TemporaryDirectory() as tmp:
        await _graded_env(tmp, None)
        os.environ.pop("RADAR_CHANNEL_ID", None)
        bot = FakeBot()
        assert await rd.digest_once(bot) is False
        assert bot.sent == []
        # and no bot at all is safe
        os.environ["RADAR_CHANNEL_ID"] = "@x"
        try:
            assert await rd.digest_once(None) is False
        finally:
            del os.environ["RADAR_CHANNEL_ID"]
    print("✓ digest gated on channel + bot presence")


async def _run_all():
    test_no_post_before_data()
    for t in (test_graded_digest_render_and_dedup, test_channel_gating):
        ot.set_clock(None)
        ot.set_market_fetcher(None)
        rd.set_clock(None)
        ra.set_clock(None)
        await t()
    ot.set_clock(None)
    ot.set_market_fetcher(None)
    rd.set_clock(None)
    ra.set_clock(None)
    print("\nAll receipts-digest tests passed ✅")


def test_all_pytest():
    asyncio.run(_run_all())


if __name__ == "__main__":
    asyncio.run(_run_all())
