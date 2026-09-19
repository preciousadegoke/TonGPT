"""Real client HTTP status handling and queue recovery; no network/runtime files."""

import importlib.util
import json
import sys
import types
from unittest.mock import AsyncMock
from pathlib import Path

import pytest


def load_source(name, relative):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    def __init__(self, status):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def text(self):
        return json.dumps({"status": "RetryableFailure", "retryable": True})

    async def json(self):
        return {"status": "Activated", "alreadyProcessed": False, "paymentId": "persisted-id"}


@pytest.mark.parametrize("provider", ["ton", "telegram_stars"])
@pytest.mark.parametrize("outage", [False, True])
async def test_http_503_retries_and_queue_recovery(monkeypatch, tmp_path, provider, outage):
    module = load_source("retry_client", "services/engine_client.py")
    client = module.EngineClient(base_url="http://unused.invalid/api")
    sent = []
    delays = []
    recovered = False

    class Session:
        def post(self, url, json, headers):
            sent.append(dict(json))
            return Response(503 if not recovered and (outage or len(sent) < 3) else 200)

    async def session():
        return Session()

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(client, "_get_session", session)
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    args = dict(telegram_id=1001, plan="Pro", provider=provider,
                external_id="same-charge", amount_ton=30, amount_stars=10000)
    result = await client.complete_payment(**args)
    assert len(sent) == 3
    assert delays == [1.0, 2.0]
    if not outage:
        assert result["ok"] and result["payment_id"] == "persisted-id"
        assert all(payload == sent[0] for payload in sent)
        return

    assert result == {"ok": False, "permanent": False, "error": 503}
    monkeypatch.setitem(sys.modules, "services.engine_client", types.SimpleNamespace(engine_client=client))
    queue = load_source("retry_queue", "services/activation_queue.py")
    queue.QUEUE_FILE = str(tmp_path / "pending.jsonl")
    queue.DEAD_LETTER_FILE = str(tmp_path / "dead.jsonl")

    async def no_notice(*args, **kwargs):
        pass

    monkeypatch.setattr(queue, "_notify_user", no_notice)
    await queue.enqueue(dict(user_id=1001, plan="Pro", provider=provider,
                             external_id="same-charge", amount_ton=30, amount_stars=10000))
    assert await queue.drain_once() == 0
    assert len(sent) == 6 and await queue.pending_count() == 1
    recovered = True
    assert await queue.drain_once() == 1
    assert len(sent) == 7 and await queue.pending_count() == 0
    assert all(payload == sent[0] for payload in sent)


@pytest.mark.parametrize('provider', ['ton', 'telegram_stars'])
@pytest.mark.parametrize('proof', [True, False])
async def test_upgrade_hold_requires_durable_proof_and_preserves_integer_units(provider, proof):
    module = load_source('upgrade_receipt_client', 'services/engine_client.py')
    client = module.EngineClient(base_url='http://unused.invalid/api')
    client._post = AsyncMock(return_value={'status': 'ReconciliationRequired', 'paymentId': 'held-1' if proof else None, 'alreadyProcessed': True})
    units = 9007199254740993  # catches accidental float conversion beyond 2**53
    result = await client.complete_payment(telegram_id=777, plan='Pro', provider=provider,
        external_id='charge', duration_days=0, quote_reference='a' * 32,
        paid_units=units, paid_at='2026-09-19T12:00:00Z')
    body = client._post.call_args.args[1]
    assert body['paidUnits'] == units and type(body['paidUnits']) is int
    assert body['durationDays'] == 0 and body['quoteReference'] == 'a' * 32
    assert body['paidAt'] == '2026-09-19T12:00:00Z'
    assert result['ok'] is False and result['permanent'] is False
    assert bool(result.get('held')) is proof
    assert bool(result.get('payment_id')) is proof
