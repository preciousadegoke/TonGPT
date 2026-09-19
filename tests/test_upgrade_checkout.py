"""Upgrade delivery boundaries: real parsers/handlers/queue, isolated transports."""
import importlib.util
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from services import checkout
from api.checkout_routes import install_checkout_routes

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = 'a' * 32
WALLET = '0:' + '11' * 32


def source(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setenv('BOT_TOKEN', 'offline-test-token')
    monkeypatch.setenv('WALLET_LINK_SIGNING_SECRET', 'offline-upgrade-test-secret')
    monkeypatch.setenv('TON_NETWORK', 'testnet')
    monkeypatch.setenv('TON_PAYMENTS_ENABLED', 'true')
    monkeypatch.setenv('MONITORED_WALLET_ADDRESS', WALLET)
    monkeypatch.delenv('TONAPI_BASE_URL', raising=False)
    engine = types.SimpleNamespace(_post=AsyncMock(), _get=AsyncMock(), complete_payment=AsyncMock())
    module = types.ModuleType('services.engine_client'); module.engine_client = engine
    monkeypatch.setitem(sys.modules, 'services.engine_client', module)
    return engine


@pytest.mark.asyncio
@pytest.mark.parametrize('rail', ['ton', 'stars'])
async def test_upgrade_ticket_uses_engine_units_and_user_bound_reference(engine, rail):
    async def quote(path, body, **kwargs):
        reference = path.rsplit('/', 1)[1]
        assert kwargs['extra_headers']['X-Checkout-Assertion'].startswith(f'co1|777|{reference}|')
        assert body == {'plan': 'Pro', 'provider': 'ton' if rail == 'ton' else 'telegram_stars'}
        return {'kind': 'upgrade', 'reference': reference, 'expectedUnits': '1333', 'expiry': '2030-01-01T00:00:00Z', 'validUntil': 1900000000}
    engine._post.side_effect = quote
    original = checkout.ton_quote(777, 'pro', WALLET) if rail == 'ton' else checkout.stars_ticket(777, 'pro')
    ticket = await checkout.prepare_ticket(original)
    assert ticket['kind'] == 'upgrade' and ticket['expected_units'] == 1333
    assert checkout.read_ticket(ticket['token'], 777)['quote_reference'] == ticket['reference']
    with pytest.raises(ValueError): checkout.read_ticket(ticket['token'], 888)
    if rail == 'ton':
        from services.ton_payments import parse_memo
        assert ticket['amount'] == '1333'
        assert parse_memo(ticket['memo'])['quote_reference'] == ticket['reference']
    else:
        assert checkout.invoice_payload(ticket).startswith('upgrade_pro|')
        assert checkout.parse_invoice(checkout.invoice_payload(ticket), 777) == ('pro', ticket['reference'])


@pytest.mark.asyncio
@pytest.mark.parametrize('result', [{'error': 503}, {'kind': 'upgrade', 'reference': 'wrong'}, {'error': 409}])
async def test_unavailable_or_conflicting_quote_cannot_prepare_payment(engine, result):
    engine._post.return_value = result
    with pytest.raises((RuntimeError, ValueError)):
        await checkout.prepare_ticket(checkout.stars_ticket(777, 'pro'))


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['valid', 'under', 'over', 'wrong-plan', 'wrong-provider', 'outage', 'expired', 'other-user', 'legacy-upgrade', 'legacy-cycle'])
async def test_stars_precheckout_fails_closed_before_collecting(engine, monkeypatch, mode):
    pay = source('isolated_upgrade_pay', 'handlers/pay.py')
    offer = {'kind': 'upgrade', 'provider': 'telegram_stars', 'targetPlan': 'Pro', 'expectedUnits': '1333'}
    engine._get.return_value = offer
    payload = f'upgrade_pro|{REFERENCE}|777'
    amount = 1333
    if mode == 'under': amount -= 1
    if mode == 'over': amount += 1
    if mode == 'wrong-plan': offer['targetPlan'] = 'Elite'
    if mode == 'wrong-provider': offer['provider'] = 'ton'
    if mode == 'outage': engine._get.side_effect = RuntimeError('offline')
    if mode == 'expired': engine._get.return_value = None
    if mode == 'other-user': payload = f'upgrade_pro|{REFERENCE}|888'
    if mode.startswith('legacy'):
        payload = 'premium_pro'; amount = 4000
        async def prepare(path, *args, **kwargs):
            return ({'kind': 'cycle'} if mode == 'legacy-cycle' else
                    {'kind': 'upgrade', 'reference': path.rsplit('/', 1)[1], 'expectedUnits': '1333', 'expiry': '2030-01-01T00:00:00Z', 'validUntil': 1900000000})
        engine._post.side_effect = prepare
    query = types.SimpleNamespace(invoice_payload=payload, currency='XTR', total_amount=amount,
                                  from_user=types.SimpleNamespace(id=777), answer=AsyncMock())
    await pay.pre_checkout_handler(query)
    assert query.answer.call_args.kwargs['ok'] is (mode in ('valid', 'legacy-cycle'))


@pytest.mark.asyncio
@pytest.mark.parametrize('timestamp', [1800000000, None, 'malformed'])
@pytest.mark.parametrize('outcome', ['held', 'queued'])
async def test_ton_upgrade_delivers_actual_amount_without_cycle_tolerance(engine, monkeypatch, timestamp, outcome):
    ton = source('isolated_upgrade_ton', 'services/ton_payments.py')
    monkeypatch.setattr(ton, '_redis', lambda: None)
    enqueue = AsyncMock()
    queue_module = types.ModuleType('services.activation_queue'); queue_module.enqueue = enqueue
    monkeypatch.setitem(sys.modules, 'services.activation_queue', queue_module)
    engine.complete_payment.return_value = ({'ok': False, 'held': True, 'payment_id': 'durable-hold'} if outcome == 'held' else {'ok': False, 'permanent': False})
    event = {'event_id': 'quoted-event', 'lt': 100, 'timestamp': timestamp, 'actions': [{
        'type': 'TonTransfer', 'status': 'ok', 'TonTransfer': {
            'amount': '1333', 'comment': f'TGU1-777-pro-{REFERENCE}', 'recipient': {'address': WALLET}}}]}
    activated, confirmed = await ton._process_one_event(event)
    assert activated == 0 and confirmed is (outcome == 'held')
    actual = engine.complete_payment.call_args.kwargs
    assert actual['duration_days'] == 0 and actual['paid_units'] == 1333
    assert actual['quote_reference'] == REFERENCE and actual['checkout_reference'] == REFERENCE
    assert actual['external_id'] == 'ton:quoted-event:0'
    assert actual['paid_at'] == (datetime.fromtimestamp(timestamp, timezone.utc).isoformat() if isinstance(timestamp, int) else None)
    if outcome == 'queued':
        queued = enqueue.call_args.args[0]
        assert queued['paid_units'] == 1333 and queued['quote_reference'] == REFERENCE and queued['paid_at'] == actual['paid_at']
    else: enqueue.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('rail', ['ton', 'telegram_stars'])
@pytest.mark.parametrize('proof', [True, False])
async def test_restart_preserves_upgrade_receipt_until_durable_hold(engine, tmp_path, rail, proof):
    def queue():
        q = source('isolated_upgrade_queue', 'services/activation_queue.py')
        q.QUEUE_FILE = str(tmp_path / 'queue.jsonl')
        q._notify_user = AsyncMock(); q._alert = AsyncMock()
        return q
    first = queue()
    receipt = dict(user_id=777, plan='Pro', provider=rail, external_id='receipt-1', duration_days=0,
                   quote_reference=REFERENCE, checkout_reference=REFERENCE, paid_units=1333, paid_at='2026-09-19T12:00:00+00:00')
    await first.enqueue(receipt)
    assert json.loads(Path(first.QUEUE_FILE).read_text())['paid_units'] == 1333
    engine.complete_payment.return_value = {'ok': False, 'held': True, 'payment_id': 'hold-1' if proof else None}
    restarted = queue()
    assert await restarted.drain_once() == 0
    restarted._notify_user.assert_not_awaited()
    assert await restarted.pending_count() == (0 if proof else 1)
    forwarded = engine.complete_payment.call_args.kwargs
    for key in ('quote_reference', 'checkout_reference', 'paid_units', 'paid_at', 'duration_days'):
        assert forwarded[key] == receipt[key]


@pytest.mark.asyncio
async def test_quote_validation_route_is_user_bound_and_fails_closed(engine):
    app = FastAPI(); install_checkout_routes(app, lambda _: {'id': 777})
    ticket = checkout.issue_ticket(777, 'pro', 'stars', REFERENCE, kind='upgrade', quote_reference=REFERENCE)
    other = checkout.issue_ticket(888, 'pro', 'stars', REFERENCE, kind='upgrade', quote_reference=REFERENCE)
    engine._get.return_value = {'kind': 'upgrade'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://offline') as client:
        assert (await client.post('/api/checkout/validate', json={'token': other['token']})).status_code == 409
        engine._get.assert_not_awaited()
        response = await client.post('/api/checkout/validate', json={'token': ticket['token']})
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        engine._get.side_effect = RuntimeError('offline')
        assert (await client.post('/api/checkout/validate', json={'token': ticket['token']})).status_code == 503
