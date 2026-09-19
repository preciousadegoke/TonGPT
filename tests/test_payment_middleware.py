"""Successful payments must reach activation even with exhausted message quota."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import Message, Update

from core.pricing import expected_stars
from utils.production_middleware import RateLimitMiddleware


ROOT = Path(__file__).resolve().parents[1]


def load_source(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def payment_dispatcher(monkeypatch, tmp_path):
    # Isolate external services; execute the real router and on-disk queue.
    engine = SimpleNamespace(
        get_user_status=AsyncMock(return_value={"tier": "free"}),
        complete_payment=AsyncMock(),
    )
    engine_module = ModuleType("services.engine_client")
    engine_module.engine_client = engine
    monkeypatch.setitem(sys.modules, "services.engine_client", engine_module)
    redis_module = ModuleType("utils.redis_conn")
    redis_module.redis_client = None
    monkeypatch.setitem(sys.modules, "utils.redis_conn", redis_module)
    queue = load_source("payment_test_queue", "services/activation_queue.py")
    queue.QUEUE_FILE = str(tmp_path / "pending.jsonl")
    monkeypatch.setitem(sys.modules, "services.activation_queue", queue)
    pay = load_source("payment_test_handler", "handlers/pay.py")

    limiter = SimpleNamespace(check_rate_limit=AsyncMock(return_value=(
        True, {"limit": 3, "remaining": 0, "reset_time": 1_800_000_000}
    )))
    reply = AsyncMock()
    monkeypatch.setattr(Message, "reply", reply)
    dispatcher = Dispatcher()
    dispatcher.message.outer_middleware(RateLimitMiddleware(limiter))
    dispatcher.include_router(pay.router)
    return dispatcher, engine, limiter, queue, reply


async def send_message(dispatcher, **fields):
    bot = Bot(token="123456:offline-test-token")
    try:
        await dispatcher.feed_update(bot, Update.model_validate({
            "update_id": 1,
            "message": {
                "message_id": 1, "date": 1_800_000_000,
                "chat": {"id": 1001, "type": "private"},
                "from": {"id": 1001, "is_bot": False, "first_name": "Payer"},
                **fields,
            },
        }))
    finally:
        await bot.session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("engine_available", [True, False], ids=["activated", "queued"])
@pytest.mark.parametrize("checkout_reference", [None, 'a' * 32], ids=['legacy-invoice', 'miniapp-invoice'])
async def test_successful_payment_bypasses_saturated_limiter(payment_dispatcher, engine_available, checkout_reference):
    dispatcher, engine, limiter, queue, reply = payment_dispatcher
    engine.complete_payment.return_value = (
        {"ok": True, "payment_id": "payment-1"} if engine_available else
        {"ok": False, "permanent": False, "error": "unreachable"}
    )
    await send_message(dispatcher, successful_payment={
        "currency": "XTR", "total_amount": expected_stars("pro"),
        "invoice_payload": "premium_pro" + (f'|{checkout_reference}|1001' if checkout_reference else ''),
        "telegram_payment_charge_id": "charge-1", "provider_payment_charge_id": "",
    })

    engine.complete_payment.assert_awaited_once_with(
        telegram_id=1001, plan="Pro", provider="telegram_stars",
        external_id="charge-1", duration_days=30,
        amount_ton=0.0, amount_stars=expected_stars("pro"),
        **({'checkout_reference': checkout_reference} if checkout_reference else {}),
    )
    if engine_available:
        assert await queue.pending_count() == 0
    else:
        records = [json.loads(line) for line in Path(queue.QUEUE_FILE).read_text().splitlines()]
        assert len(records) == 1
        assert records[0]["external_id"] == "charge-1"
        assert records[0]["user_id"] == 1001
        assert records[0]["amount_stars"] == expected_stars("pro")
        assert records[0].get('checkout_reference') == checkout_reference
    limiter.check_rate_limit.assert_not_awaited()
    engine.get_user_status.assert_not_awaited()
    reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_regular_message_is_still_throttled(payment_dispatcher):
    dispatcher, engine, limiter, queue, reply = payment_dispatcher
    await send_message(dispatcher, text="/pay")
    limiter.check_rate_limit.assert_awaited_once_with(1001, "free")
    engine.get_user_status.assert_awaited_once()
    engine.complete_payment.assert_not_awaited()
    assert await queue.pending_count() == 0
    reply.assert_awaited_once()
    assert "Rate limit exceeded" in reply.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('amount', [1332, 1333, 1334])
@pytest.mark.parametrize('outcome', ['held', 'queued'])
async def test_upgrade_receipt_is_never_dropped_by_cycle_price_or_quota(payment_dispatcher, amount, outcome):
    dispatcher, engine, limiter, queue, reply = payment_dispatcher
    engine.complete_payment.return_value = ({'ok': False, 'held': True, 'payment_id': 'held-1'}
                                          if outcome == 'held' else {'ok': False, 'permanent': False})
    reference = 'a' * 32
    await send_message(dispatcher, successful_payment={
        'currency': 'XTR', 'total_amount': amount, 'invoice_payload': f'upgrade_pro|{reference}|1001',
        'telegram_payment_charge_id': 'upgrade-charge', 'provider_payment_charge_id': '',
    })
    forwarded = engine.complete_payment.call_args.kwargs
    assert forwarded['paid_units'] == amount and forwarded['amount_stars'] == amount
    assert forwarded['quote_reference'] == reference and forwarded['duration_days'] == 0
    assert forwarded['paid_at'] and forwarded['external_id'] == 'upgrade-charge'
    limiter.check_rate_limit.assert_not_awaited()
    assert await queue.pending_count() == (1 if outcome == 'queued' else 0)
    if outcome == 'held': assert 'reconciliation' in reply.call_args.args[0].lower()
