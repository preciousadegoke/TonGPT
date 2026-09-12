"""Checkpoint regressions: fake chain, Engine and Redis; no runtime data writes."""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import httpx
import pytest
from structlog.testing import capture_logs

from test_ton_payments import TEST_WALLET, FakeEngine, _load_tp, _recipient_event


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.writes_enabled = True

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, **kwargs):
        if not self.writes_enabled:
            return False
        self.values[key] = value
        return True

    def exists(self, key):
        return key in self.values


def payment(lt):
    event = _recipient_event({"address": TEST_WALLET})
    event.update(event_id=f"event-{lt}", lt=lt, in_progress=False)
    return event


@pytest.fixture
def monitor(monkeypatch):
    engine = FakeEngine()
    redis = MemoryRedis()
    chain = [payment(100)]
    queued = []
    cursors = []

    async def enqueue(record):
        queued.append(record)

    async def no_notice(*args):
        pass

    async def fetch(limit=50, before_lt=None):
        cursors.append(before_lt)
        return [ev for ev in chain if before_lt is None or ev["lt"] < before_lt][:limit]

    monkeypatch.setitem(sys.modules, "services.engine_client",
                        types.SimpleNamespace(engine_client=engine))
    queue = types.SimpleNamespace(enqueue=enqueue)
    monkeypatch.setitem(sys.modules, "services.activation_queue", queue)

    def restart():
        tp = _load_tp()
        monkeypatch.setattr(tp, "_redis", lambda: redis)
        monkeypatch.setattr(tp, "fetch_incoming_events", fetch)
        monkeypatch.setattr(tp, "_notify_user", no_notice)
        monkeypatch.setattr(tp, "_notify_underpaid", no_notice)
        return tp

    return types.SimpleNamespace(tp=restart(), restart=restart, engine=engine,
                                 redis=redis, chain=chain, queued=queued,
                                 queue=queue, cursors=cursors)


async def test_failed_persistence_checkpoint_retry_after_restart(monitor):
    m = monitor
    m.chain[:] = [payment(101), payment(100)]
    complete = m.engine.complete_payment

    async def fail_second(**kwargs):
        if kwargs["external_id"] == "ton:event-100:0":
            return {"ok": False, "permanent": False}
        return await complete(**kwargs)

    async def fail_queue(record):
        raise OSError("simulated fsync failure")

    m.engine.complete_payment = fail_second
    m.queue.enqueue = fail_queue
    assert await m.tp.process_events_once() == 1
    assert m.tp._get_high_water_lt() is None
    assert set(m.engine.activated) == {"ton:event-101:0"}

    m.engine.complete_payment = complete
    m.tp = m.restart()
    assert await m.tp.process_events_once() == 1
    assert m.tp._get_high_water_lt() == 101
    assert await m.tp.process_events_once() == 0
    assert len(m.engine.activated) == 2


async def test_queue_ack_and_legacy_done_marker_are_not_commit_proof(monitor):
    m = monitor
    m.redis.values["ton_done:ton:event-100:0"] = "1"
    m.engine.up = False
    assert await m.tp.process_events_once() == 0
    assert len(m.queued) == 1
    assert m.tp._get_high_water_lt() is None
    m.engine.up = True
    m.tp = m.restart()
    assert await m.tp.process_events_once() == 1
    assert m.tp._get_high_water_lt() == 100
    assert await m.tp.process_events_once() == 0
    assert len(m.engine.activated) == 1


async def test_success_without_payment_record_does_not_advance(monitor):
    async def false_ack(**kwargs):
        return {"ok": True, "already_processed": True, "payment_id": None}

    monitor.engine.complete_payment = false_ack
    assert await monitor.tp.process_events_once() == 0
    assert monitor.tp._get_high_water_lt() is None


async def test_lost_engine_response_replays_without_second_activation(monitor):
    m = monitor
    complete = m.engine.complete_payment

    async def commit_then_lose_response(**kwargs):
        await complete(**kwargs)
        return {"ok": False, "permanent": False, "error": "response lost"}

    m.engine.complete_payment = commit_then_lose_response
    assert await m.tp.process_events_once() == 0
    assert m.tp._get_high_water_lt() is None
    assert len(m.engine.activated) == 1
    m.engine.complete_payment = complete
    m.tp = m.restart()
    assert await m.tp.process_events_once() == 0
    assert m.tp._get_high_water_lt() == 100
    assert len(m.engine.activated) == 1


async def test_failure_preserves_existing_confirmed_checkpoint(monitor):
    m = monitor
    assert await m.tp.process_events_once() == 1
    assert m.tp._get_high_water_lt() == 100
    m.chain.insert(0, payment(101))
    m.engine.up = False
    assert await m.tp.process_events_once() == 0
    assert m.tp._get_high_water_lt() == 100
    m.engine.up = True
    assert await m.tp.process_events_once() == 1
    assert m.tp._get_high_water_lt() == 101
    assert len(m.engine.activated) == 2


@pytest.mark.parametrize("loser", ["replay", "new"])
async def test_false_duplicate_during_overlapping_replay_is_recovered(monitor, monkeypatch, loser):
    """Exercise real response normalization; simulate either request losing in DB.

    This verifies scanner recovery from Fix 3's response, not the EF race itself.
    """
    m = monitor
    m.chain[:] = [payment(50)]
    assert await m.tp.process_events_once() == 1
    assert m.tp._get_high_water_lt() == 50
    m.chain[:] = [payment(100), payment(50)]

    # Load the real client without replacing other tests' installed module fake.
    spec = importlib.util.spec_from_file_location(
        "checkpoint_response_client",
        Path(__file__).resolve().parents[1] / "services/engine_client.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = module.EngineClient(base_url="http://unused.invalid/api")
    commit = m.engine.complete_payment
    arrived = set()
    overlapping = asyncio.Event()
    failed_id = "ton:event-100:0" if loser == "replay" else "ton:event-101:0"
    failures_left = 1 if loser == "replay" else 2

    async def post(endpoint, data):
        nonlocal failures_left
        assert endpoint == "Payment/complete"
        external_id = data["externalId"]
        arrived.add(external_id)
        if len(arrived) == 2:
            overlapping.set()
        await overlapping.wait()
        if external_id == failed_id and failures_left:
            failures_left -= 1
            # Exact response shape from the still-unfixed DbUpdateException catch.
            return {"status": "AlreadyProcessed", "alreadyProcessed": True, "paymentId": None}
        result = await commit(
            telegram_id=data["telegramId"], plan=data["plan"], provider=data["provider"],
            external_id=external_id, duration_days=data["durationDays"], amount_ton=data["amountTon"],
        )
        return {"status": result["status"], "alreadyProcessed": result["already_processed"],
                "paymentId": result["payment_id"]}

    monkeypatch.setattr(client, "_post", post)  # no HTTP or live database
    monkeypatch.setattr(m.engine, "complete_payment", client.complete_payment)
    with capture_logs() as logs:
        replay_count, new_result = await asyncio.wait_for(asyncio.gather(
            m.tp.process_events_once(),
            client.complete_payment(777, "Pro", "ton", "ton:event-101:0", amount_ton=30),
        ), timeout=10)
        checkpoint = 50 if loser == "replay" else 100
        assert replay_count == (0 if loser == "replay" else 1)
        assert m.tp._get_high_water_lt() == checkpoint
        assert new_result["ok"] is True
        assert bool(new_result["payment_id"]) == (loser == "replay")

        # The next chain scan sees the new payment even if another caller/queue
        # mistook its false acknowledgement for success and dropped its retry.
        m.chain[:] = [payment(101), payment(100), payment(50)]
        if loser == "new":
            assert await m.tp.process_events_once() == 0
            assert m.tp._get_high_water_lt() == checkpoint
        assert any(row["event"] == "ton_payment_unconfirmed_ack" for row in logs)
        assert failed_id not in m.engine.activated
        assert await m.tp.process_events_once() == 1
        # A resumed scan retains its original upper bound; the next poll covers
        # a newer arrival even when replay has already confirmed that payment.
        assert m.tp._get_high_water_lt() == (100 if loser == "replay" else 101)
        assert await m.tp.process_events_once() == 0
        assert m.tp._get_high_water_lt() == 101
        assert set(m.engine.activated) == {"ton:event-50:0", "ton:event-100:0", "ton:event-101:0"}


async def test_page_budget_resumes_without_skipping_gap(monitor, monkeypatch):
    m = monitor
    m.chain[:] = [payment(lt) for lt in range(125, 0, -1)]
    monkeypatch.setenv("TON_MONITOR_MAX_PAGES", "1")
    assert await m.tp.process_events_once() == 50
    assert m.tp._get_high_water_lt() is None
    assert await m.tp.process_events_once() == 50
    assert m.tp._get_high_water_lt() is None
    # New arrivals must be processed on the next scan, outside this scan's bound.
    m.chain.insert(0, payment(126))
    assert await m.tp.process_events_once() == 25
    assert m.tp._get_high_water_lt() is None
    assert await m.tp.process_events_once() == 0  # explicit end of history
    assert m.tp._get_high_water_lt() == 125
    assert await m.tp.process_events_once() == 1
    assert m.tp._get_high_water_lt() == 126
    assert len(m.engine.activated) == 126
    assert m.cursors[:4] == [None, 76, 26, 1]


async def test_restart_during_pagination_replays_committed_page(monitor, monkeypatch):
    m = monitor
    m.chain[:] = [payment(lt) for lt in range(75, 0, -1)]
    monkeypatch.setenv("TON_MONITOR_MAX_PAGES", "1")
    assert await m.tp.process_events_once() == 50
    assert m.tp._get_high_water_lt() is None
    m.tp = m.restart()
    assert await m.tp.process_events_once() == 25
    assert m.tp._get_high_water_lt() == 75
    assert len(m.engine.activated) == 75


async def test_later_page_fetch_failure_keeps_checkpoint(monitor, monkeypatch):
    m = monitor
    m.chain[:] = [payment(lt) for lt in range(75, 0, -1)]
    fetch = m.tp.fetch_incoming_events

    async def failing_fetch(limit=50, before_lt=None):
        if before_lt is not None:
            raise httpx.ReadTimeout("simulated page timeout")
        return await fetch(limit, before_lt)

    monkeypatch.setattr(m.tp, "fetch_incoming_events", failing_fetch)
    with pytest.raises(httpx.ReadTimeout):
        await m.tp.process_events_once()
    assert m.tp._get_high_water_lt() is None
    monkeypatch.setattr(m.tp, "fetch_incoming_events", fetch)
    assert await m.tp.process_events_once() == 25
    assert m.tp._get_high_water_lt() == 75
    assert len(m.engine.activated) == 75


@pytest.mark.parametrize("bad_lt", [None, "bad", 0, -1])
async def test_invalid_cursor_blocks_checkpoint(monitor, monkeypatch, bad_lt):
    event = payment(100)
    event["lt"] = bad_lt

    async def fetch(**kwargs):
        return [event]

    monkeypatch.setattr(monitor.tp, "fetch_incoming_events", fetch)
    with pytest.raises(ValueError, match="cursor"):
        await monitor.tp.process_events_once()
    assert monitor.tp._get_high_water_lt() is None
    assert monitor.engine.calls == 0


@pytest.mark.parametrize("lts", [[99, 100], [100, 100]])
async def test_non_descending_page_blocks_checkpoint(monitor, monkeypatch, lts):
    async def fetch(**kwargs):
        return [payment(lt) for lt in lts]

    monkeypatch.setattr(monitor.tp, "fetch_incoming_events", fetch)
    with pytest.raises(ValueError, match="cursor"):
        await monitor.tp.process_events_once()
    assert monitor.tp._get_high_water_lt() is None
    assert monitor.engine.calls == 0


async def test_in_progress_event_blocks_checkpoint(monitor):
    monitor.chain[0]["in_progress"] = True
    assert await monitor.tp.process_events_once() == 0
    assert monitor.tp._get_high_water_lt() is None
    assert monitor.engine.calls == 0
    monitor.chain[0]["in_progress"] = False
    assert await monitor.tp.process_events_once() == 1
    assert monitor.tp._get_high_water_lt() == 100


async def test_checkpoint_write_failure_replays_safely(monitor):
    monitor.redis.writes_enabled = False
    with capture_logs() as logs:
        assert await monitor.tp.process_events_once() == 1
    assert monitor.tp._get_high_water_lt() is None
    assert any(row["event"] == "ton_checkpoint_write_failed" for row in logs)
    monitor.redis.writes_enabled = True
    monitor.tp = monitor.restart()
    assert await monitor.tp.process_events_once() == 0
    assert monitor.tp._get_high_water_lt() == 100
    assert len(monitor.engine.activated) == 1


async def test_checkpoint_is_scoped_and_legacy_checkpoint_is_ignored(monitor, monkeypatch):
    m = monitor
    m.redis.values["ton_monitor_high_lt"] = "10000"
    assert await m.tp.process_events_once() == 1
    assert m.tp._get_high_water_lt() == 100
    monkeypatch.setenv("MONITORED_WALLET_ADDRESS", "0:" + "cd" * 32)
    assert m.tp._get_high_water_lt() is None
    monkeypatch.setenv("MONITORED_WALLET_ADDRESS", TEST_WALLET)
    monkeypatch.setenv("TON_NETWORK", "mainnet")
    assert m.tp._get_high_water_lt() is None
    monkeypatch.setenv("TON_NETWORK", "testnet")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://other.example/v2")
    assert m.tp._get_high_water_lt() is None


@pytest.mark.parametrize("response", [None, {}, {"events": None}, {"events": {}}, {"events": [None]}, "timeout"])
async def test_fetch_errors_are_not_end_of_history(monkeypatch, response):
    tp = _load_tp()

    async def handler(request):
        if response == "timeout":
            raise httpx.ReadTimeout("simulated timeout", request=request)
        return httpx.Response(200, json=response)

    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises((ValueError, httpx.ReadTimeout)):
        await tp.fetch_incoming_events()
    assert tp._consecutive_fetch_failures == 1


async def test_invalid_wallet_logs_error_from_monitor(monitor, monkeypatch):
    monkeypatch.setenv("MONITORED_WALLET_ADDRESS", "invalid-wallet")

    async def stop_after_iteration(*args):
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", stop_after_iteration)
    with capture_logs() as logs, pytest.raises(asyncio.CancelledError):
        await monitor.tp.monitor_loop(interval=1)
    assert any(row["event"] == "ton_monitor_error" and row["log_level"] == "error"
               and row.get("err") for row in logs)
    assert monitor.engine.calls == 0
