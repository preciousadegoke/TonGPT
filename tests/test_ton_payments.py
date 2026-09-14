"""
tests/test_ton_payments.py — TON on-chain payment logic (money-critical).

Runnable two ways:
    pytest tests/test_ton_payments.py -v
    python tests/test_ton_payments.py

Covers:
  * canonical pricing is internally consistent (core/pricing.py)
  * memo encode/decode round-trips and rejects malformed memos
  * amount validation (exact / over / under / tolerance)
  * TONAPI event parsing is shape-tolerant
  * end-to-end monitor pass activates once and is idempotent on replay
  * underpayment is never activated

The engine is faked via sys.modules so no aiohttp / live Postgres is needed.
httpx is never imported because we monkeypatch fetch_incoming_events.
"""

import asyncio
import os
import sys
import types
from pathlib import Path

import pytest
from tonsdk.utils import Address, InvalidAddressError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import pricing  # noqa: E402

TEST_WALLET = "0:" + "ab" * 32


# --------------------------------------------------------------------------- #
# Fake engine (mirrors idempotent complete_payment contract)
# --------------------------------------------------------------------------- #
class FakeEngine:
    def __init__(self):
        self.up = True
        self.activated = {}  # external_id -> plan
        self.calls = 0

    async def complete_payment(self, telegram_id, plan, provider, external_id,
                               duration_days=30, amount_ton=0.0, amount_stars=0,
                               max_attempts=3, checkout_reference=None):
        self.calls += 1
        if not self.up:
            return {"ok": False, "permanent": False, "error": "unreachable"}
        already = external_id in self.activated
        self.activated[external_id] = plan
        return {
            "ok": True, "already_processed": already,
            "status": "AlreadyProcessed" if already else "Activated",
            "payment_id": f"pid-{external_id}", "plan": plan,
            "expiry": "2026-12-31T00:00:00Z", "permanent": False,
        }

    async def get_user_status(self, telegram_id):
        return {"plan": "Free"}


def _install_fakes() -> FakeEngine:
    fake_engine = FakeEngine()
    mod = types.ModuleType("services.engine_client")
    mod.engine_client = fake_engine
    mod.EngineServerError = type("EngineServerError", (Exception,), {})
    sys.modules["services.engine_client"] = mod
    return fake_engine


def _load_tp():
    for k in list(os.environ):
        if k.startswith("TON_") or k == "MONITORED_WALLET_ADDRESS":
            del os.environ[k]
    os.environ["TON_PAYMENTS_ENABLED"] = "true"
    os.environ["TON_NETWORK"] = "testnet"
    os.environ["MONITORED_WALLET_ADDRESS"] = TEST_WALLET
    if "services.ton_payments" in sys.modules:
        del sys.modules["services.ton_payments"]
    import importlib
    tp = importlib.import_module("services.ton_payments")
    # Unit tests must not read or write a developer's Redis payment state.
    # Replay deduplication here is deliberately exercised through FakeEngine.
    tp._redis = lambda: None
    return tp


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_pricing_consistent():
    assert set(pricing.PLANS) == set(pricing.PLAN_PRICES_USD)
    for key, plan in pricing.PLANS.items():
        assert plan["price_nanoton"] == int(plan["price_ton"] * 1e9), key
        assert pricing.plan_to_engine(key) in ("Starter", "Pro", "ProPlus", "Elite")
        assert pricing.expected_nanoton(key) == plan["price_nanoton"]
    print("✓ canonical pricing is internally consistent")


def test_memo_roundtrip_and_rejects():
    tp = _load_tp()
    for key in pricing.PLAN_ORDER:
        memo = tp.generate_memo(123456, key)
        parsed = tp.parse_memo(memo)
        assert parsed == {"user_id": 123456, "plan_key": key, "nonce": memo.split("-")[3]}
    # malformed / hostile inputs
    for bad in ["", None, "hello world", "TGP1-abc-pro-xx", "TGP1-1-unknownplan-xx",
                "TGP9-1-pro-xx", "TGP1-1-pro", "random comment"]:
        assert tp.parse_memo(bad) is None, bad
    print("✓ memo round-trips and rejects malformed/hostile memos")


def test_amount_validation():
    tp = _load_tp()
    exp = pricing.expected_nanoton("pro")  # 30 TON
    assert tp.validate_amount(exp, "pro") is True              # exact
    assert tp.validate_amount(exp + 5_000_000_000, "pro") is True   # overpay ok
    assert tp.validate_amount(int(exp * 0.99), "pro") is True       # within 2% tol
    assert tp.validate_amount(int(exp * 0.90), "pro") is False      # underpay rejected
    assert tp.validate_amount(exp, "nope") is False                 # unknown plan
    print("✓ amount validation: exact/over/tolerance pass, underpay/unknown rejected")


def test_extract_transfers_shape_tolerant():
    tp = _load_tp()
    events = [
        {"event_id": "ev1", "actions": [
            {"type": "TonTransfer", "status": "ok",
             "TonTransfer": {"amount": "30000000000", "comment": "TGP1-1-pro-aa11bb",
                             "recipient": {"address": TEST_WALLET}}}]},
        {"event_id": "ev2", "actions": [
            {"type": "tonTransfer",  # alt casing
             "tonTransfer": {"amount": "10000000000", "comment": "TGP1-2-starter-cc22dd",
                             "recipient": {"address": TEST_WALLET}}}]},
        {"event_id": "ev3", "actions": [
            {"type": "JettonTransfer", "JettonTransfer": {"amount": "1"}}]},  # ignored
        {"event_id": "ev4", "actions": [
            {"type": "TonTransfer", "status": "failed",
             "TonTransfer": {"amount": "30000000000", "comment": "TGP1-3-pro-ee33ff",
                             "recipient": {"address": TEST_WALLET}}}]},  # ignored
    ]
    transfers = tp.extract_transfers(events)
    ids = {t["event_id"] for t in transfers}
    assert ids == {"ev1", "ev2"}, ids
    print("✓ extract_transfers is shape-tolerant and filters non-payments")


async def test_monitor_activates_once_idempotent():
    engine = _install_fakes()
    tp = _load_tp()

    async def fake_fetch(limit=50, before_lt=None):
        if before_lt is not None:
            return []
        return [
            {"event_id": "evX", "lt": 100, "actions": [
                {"type": "TonTransfer", "status": "ok",
                 "TonTransfer": {"amount": "60000000000", "comment": "TGP1-777-pro_plus-abc123",
                                 "recipient": {"address": TEST_WALLET}}}]},
        ]
    tp.fetch_incoming_events = fake_fetch

    first = await tp.process_events_once()
    second = await tp.process_events_once()   # replay must not double-activate
    assert first == 1, first
    assert second == 0, second
    # PAY-004: per-transfer idempotency key is event_id + action index.
    assert engine.activated == {"ton:evX:0": "ProPlus"}
    print("✓ monitor activates once and is idempotent on replay")


async def test_underpayment_never_activates():
    engine = _install_fakes()
    tp = _load_tp()

    async def fake_fetch(limit=50, before_lt=None):
        if before_lt is not None:
            return []
        return [
            {"event_id": "evLow", "lt": 100, "actions": [
                {"type": "TonTransfer", "status": "ok",
                 "TonTransfer": {"amount": "1000000000", "comment": "TGP1-9-elite-zz99zz",
                                 "recipient": {"address": TEST_WALLET}}}]},  # 1 TON for Elite
        ]
    tp.fetch_incoming_events = fake_fetch

    activated = await tp.process_events_once()
    assert activated == 0
    assert engine.activated == {}
    print("✓ underpayment is never activated")


def _recipient_event(recipient):
    return {"event_id": "recipient_check", "lt": 100, "actions": [{
        "type": "TonTransfer", "status": "ok",
        "TonTransfer": {"amount": str(pricing.expected_nanoton("pro")),
                        "comment": "TGP1-777-pro-abc123", "recipient": recipient},
    }]}


async def test_wrong_or_malformed_recipient_never_activates():
    friendly = Address(TEST_WALLET).to_string(True, True, True)
    bad_crc = friendly[:-1] + ("A" if friendly[-1] != "A" else "B")
    recipients = [
        {"address": "0:" + "cd" * 32},  # different wallet
        {"address": "-1:" + "ab" * 32},  # same hash, different workchain
        None, {}, {"address": None}, {"address": 123},
        {"address": ""}, {"address": "not-an-address"},
        {"address": "0:" + "zz" * 32}, {"address": bad_crc},
        TEST_WALLET, [],  # recipient must be an AccountAddress object
    ]
    for recipient in recipients:
        engine = _install_fakes()
        tp = _load_tp()
        event = _recipient_event(recipient)

        async def fake_fetch(limit=50, before_lt=None):
            return [event] if before_lt is None else []

        tp.fetch_incoming_events = fake_fetch
        assert await tp.process_events_once() == 0, recipient
        assert engine.calls == 0, recipient
        assert engine.activated == {}, recipient

    # A completely absent field must not fall back to the event's account.
    del event["actions"][0]["TonTransfer"]["recipient"]
    event["account"] = {"address": TEST_WALLET}
    assert await tp.process_events_once() == 0
    assert engine.calls == 0


def test_recipient_address_formats_are_equivalent():
    tp = _load_tp()
    address = Address(TEST_WALLET)
    forms = [TEST_WALLET, TEST_WALLET.upper()] + [
        address.to_string(True, url_safe, bounceable, test_only)
        for url_safe in (False, True)
        for bounceable in (False, True)
        for test_only in (False, True)
    ]
    for configured in forms:
        os.environ["MONITORED_WALLET_ADDRESS"] = configured
        for recipient in forms:
            transfers = tp.extract_transfers([_recipient_event({"address": recipient})])
            assert len(transfers) == 1, (configured, recipient)

    # The documented PAYMENT_WALLET_ADDRESS fallback uses the same comparison.
    os.environ.pop("MONITORED_WALLET_ADDRESS")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("PAYMENT_WALLET_ADDRESS", forms[-1])
        assert len(tp.extract_transfers([_recipient_event({"address": TEST_WALLET})])) == 1


async def test_mixed_event_preserves_incoming_action_id():
    engine = _install_fakes()
    tp = _load_tp()
    outgoing = _recipient_event({"address": "0:" + "cd" * 32})
    outgoing["actions"][0]["TonTransfer"]["sender"] = {"address": TEST_WALLET}
    incoming = _recipient_event({"address": Address(TEST_WALLET).to_string(True, True, False)})
    outgoing["actions"].extend(incoming["actions"])

    async def fake_fetch(limit=50, before_lt=None):
        return [outgoing] if before_lt is None else []

    tp.fetch_incoming_events = fake_fetch
    assert await tp.process_events_once() == 1
    assert await tp.process_events_once() == 0
    assert engine.activated == {"ton:recipient_check:1": "Pro"}


def test_invalid_monitored_wallet_stops_processing():
    tp = _load_tp()
    with pytest.MonkeyPatch.context() as patch:
        for bad_address in ("", "not-an-address", "0:" + "zz" * 32):
            patch.setenv("MONITORED_WALLET_ADDRESS", bad_address)
            patch.setenv("PAYMENT_WALLET_ADDRESS", bad_address)
            with pytest.raises((InvalidAddressError, ValueError)):
                tp.extract_transfers([_recipient_event({"address": TEST_WALLET})])


SYNC_TESTS = [test_pricing_consistent, test_memo_roundtrip_and_rejects,
              test_amount_validation, test_extract_transfers_shape_tolerant,
              test_recipient_address_formats_are_equivalent,
              test_invalid_monitored_wallet_stops_processing]
ASYNC_TESTS = [test_monitor_activates_once_idempotent, test_underpayment_never_activates,
               test_wrong_or_malformed_recipient_never_activates,
               test_mixed_event_preserves_incoming_action_id]


async def _run_all():
    for t in SYNC_TESTS:
        t()
    for t in ASYNC_TESTS:
        await t()
    print("\nAll TON payment tests passed ✅")


# pytest entry points
def test_pricing_consistent_pytest(): test_pricing_consistent()
def test_async_pytest(): asyncio.run(_run_all())


if __name__ == "__main__":
    asyncio.run(_run_all())
