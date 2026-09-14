import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from services import checkout
from api.checkout_routes import install_checkout_routes

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setenv('BOT_TOKEN', 'test-bot-token')
    monkeypatch.setenv('WALLET_LINK_SIGNING_SECRET', 'checkout-test-signing-secret-not-live')
    monkeypatch.setenv('TON_NETWORK', 'testnet')
    monkeypatch.setenv('TON_PAYMENTS_ENABLED', 'true')
    monkeypatch.setenv('MONITORED_WALLET_ADDRESS', '0:' + '11' * 32)
    monkeypatch.delenv('TONAPI_BASE_URL', raising=False)


def test_quotes_reuse_exact_monitor_format_and_canonical_amount():
    from services import ton_payments as ton
    ticket = checkout.ton_quote(777, 'pro_plus', '0:' + '22' * 32)
    parsed = ton.parse_memo(ticket['memo'])
    assert parsed['user_id'] == 777 and parsed['plan_key'] == 'pro_plus'
    assert len(parsed['nonce']) == 6 and int(parsed['nonce'], 16) >= 0
    assert ticket['reference'] == ticket['memo']
    assert ticket['amount'] == '60000000000' and ticket['network'] == 'testnet'
    assert checkout.read_ticket(ticket['token'], 777)['reference'] == ticket['reference']


def test_disabled_or_inconsistent_network_cannot_quote(monkeypatch):
    monkeypatch.setenv('TON_PAYMENTS_ENABLED', 'false')
    with pytest.raises(ValueError, match='disabled'):
        checkout.ton_quote(777, 'pro', '0:' + '22' * 32)
    monkeypatch.setenv('TONAPI_BASE_URL', 'https://tonapi.io/v2')
    with pytest.raises(ValueError, match='does not match'):
        checkout.ton_config()


def test_ticket_and_invoice_are_bound_to_payer(monkeypatch):
    ticket = checkout.stars_ticket(777, 'pro')
    assert checkout.parse_invoice(checkout.invoice_payload(ticket), 777) == ('pro', ticket['reference'])
    assert checkout.parse_invoice('premium_pro', 777) == ('pro', None)
    assert checkout.parse_invoice('pro', 777) == ('pro', None)
    with pytest.raises(ValueError):
        checkout.parse_invoice(checkout.invoice_payload(ticket), 888)
    with pytest.raises(ValueError):
        checkout.read_ticket(ticket['token'], 888)
    with pytest.raises(ValueError):
        checkout.read_ticket(ticket['token'] + '0', 777)
    monkeypatch.setattr(checkout.time, 'time', lambda: ticket['expires'] + 1)
    with pytest.raises(ValueError):
        checkout.read_ticket(ticket['token'], 777)


@pytest.mark.asyncio
async def test_status_requires_engine_proof_and_uses_user_assertion(monkeypatch):
    ticket = checkout.stars_ticket(777, 'pro')
    transport = AsyncMock(return_value={'status': 'activated', 'paymentId': 'id', 'entitlementActive': True})
    module = types.ModuleType('services.engine_client')
    module.engine_client = types.SimpleNamespace(_get=transport)
    monkeypatch.setitem(sys.modules, 'services.engine_client', module)
    result = await checkout.checkout_status(ticket)
    assert result['paymentId'] == 'id'
    path = transport.call_args.args[0]
    assertion = transport.call_args.kwargs['extra_headers']['X-Checkout-Assertion']
    assert path == 'Checkout/status/' + ticket['reference']
    assert assertion.startswith(f"co1|777|{ticket['reference']}|")
    transport.return_value = {'status': 'activated'}
    with pytest.raises(RuntimeError, match='persisted'):
        await checkout.checkout_status(ticket)
    transport.return_value = {}
    with pytest.raises(RuntimeError):
        await checkout.checkout_status(ticket)


@pytest.mark.asyncio
async def test_routes_scope_user_and_do_not_cache(monkeypatch):
    app = FastAPI()
    def verified(value):
        if value != 'valid-user-777':
            raise ValueError('invalid')
        return {'id': 777}
    install_checkout_routes(app, verified)
    probe = AsyncMock(return_value={'status': 'pending'})
    monkeypatch.setattr(checkout, 'checkout_status', probe)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        own = checkout.stars_ticket(777, 'pro')
        other = checkout.stars_ticket(888, 'pro')
        assert (await client.post('/api/checkout/status', json={'token': own['token']})).status_code == 401
        headers = {'X-Telegram-Init-Data': 'valid-user-777'}
        denied = await client.post('/api/checkout/status', headers=headers, json={'token': other['token'], 'user_id': 888})
        assert denied.status_code == 403
        probe.assert_not_awaited()
        allowed = await client.post('/api/checkout/status', headers=headers, json={'token': own['token']})
        assert allowed.status_code == 200 and allowed.headers['cache-control'] == 'no-store'
        assert probe.call_args.args[0]['user_id'] == 777
        probe.side_effect = RuntimeError('offline')
        assert (await client.post('/api/checkout/status', headers=headers, json={'token': own['token']})).status_code == 503


@pytest.mark.asyncio
async def test_ton_transaction_hash_comes_from_chain_not_message(monkeypatch):
    ticket = checkout.ton_quote(777, 'pro', '0:' + '22' * 32)
    transport = AsyncMock(return_value={'status': 'pending'})
    module = types.ModuleType('services.engine_client')
    module.engine_client = types.SimpleNamespace(_get=transport)
    monkeypatch.setitem(sys.modules, 'services.engine_client', module)
    message_hash, transaction_hash = '33' * 32, '44' * 32
    response = httpx.Response(200, json={'hash': transaction_hash, 'account': {'address': ticket['sender']}}, request=httpx.Request('GET', 'https://testnet.tonapi.io'))
    request_get = AsyncMock(return_value=response)
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        get = request_get
    monkeypatch.setattr(checkout.httpx, 'AsyncClient', Client)
    result = await checkout.checkout_status(ticket, message_hash)
    assert result['transaction_hash'] == transaction_hash and result['status'] == 'pending'
    assert request_get.call_args.args[0] == f'https://testnet.tonapi.io/v2/blockchain/messages/{message_hash}/transaction'


@pytest.mark.asyncio
async def test_checkout_reference_survives_queue_restart(monkeypatch, tmp_path):
    def load_queue():
        spec = importlib.util.spec_from_file_location('isolated_checkout_queue', ROOT / 'services/activation_queue.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.QUEUE_FILE = str(tmp_path / 'pending.jsonl')
        return module
    first = load_queue()
    await first.enqueue({'user_id': 777, 'plan': 'Pro', 'provider': 'telegram_stars', 'external_id': 'charge-1',
                         'checkout_reference': 'reference-1', 'amount_stars': 4000})
    record = json.loads(Path(first.QUEUE_FILE).read_text())
    assert record['checkout_reference'] == 'reference-1'
    complete = AsyncMock(return_value={'ok': True, 'payment_id': 'persisted'})
    engine = types.ModuleType('services.engine_client')
    engine.engine_client = types.SimpleNamespace(complete_payment=complete)
    monkeypatch.setitem(sys.modules, 'services.engine_client', engine)
    second = load_queue()
    second._notify_user = AsyncMock()
    assert await second.drain_once() == 1
    assert complete.call_args.kwargs['checkout_reference'] == 'reference-1'
    assert complete.call_args.kwargs['external_id'] == 'charge-1'
