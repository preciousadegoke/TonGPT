"""Checkout correlation and read-only verification. Never activates a payment."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from urllib.parse import quote

import httpx


def _secret():
    value = os.getenv('WALLET_LINK_SIGNING_SECRET', '')
    if not value:
        raise RuntimeError('Checkout signing is not configured')
    return value.encode()


def issue_ticket(user_id, plan, rail, reference, **extra):
    data = dict(user_id=int(user_id), plan=plan, rail=rail, reference=reference,
                expires=int(time.time()) + 7 * 86400, **extra)
    encoded = base64.urlsafe_b64encode(json.dumps(data, separators=(',', ':')).encode()).decode()
    signature = hmac.new(_secret(), b'checkout-ticket:' + encoded.encode(), hashlib.sha256).hexdigest()
    return {**data, 'token': encoded + '.' + signature}


def read_ticket(token, user_id):
    if not isinstance(token, str) or len(token) > 4096:
        raise ValueError('Invalid checkout token')
    try:
        encoded, signature = token.split('.')
        expected = hmac.new(_secret(), b'checkout-ticket:' + encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError('Invalid checkout signature')
        data = json.loads(base64.urlsafe_b64decode(encoded))
        if data['user_id'] != int(user_id) or data['expires'] <= time.time():
            raise ValueError('Checkout belongs to another user or has expired')
        return data
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid checkout token') from exc


def engine_assertion(user_id, reference):
    body = f'co1|{int(user_id)}|{reference}|{int(time.time()) + 60}|{secrets.token_hex(8)}'
    return body + '|' + hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()


def ton_config():
    from services import ton_payments as ton
    network = ton.network()
    if network not in ('mainnet', 'testnet'):
        raise ValueError('Invalid TON_NETWORK')
    expected_api = 'https://tonapi.io/v2' if network == 'mainnet' else 'https://testnet.tonapi.io/v2'
    # Avoid silently quoting a network different from the monitor's provider.
    if ton.tonapi_base().rstrip('/') != expected_api:
        raise ValueError('TONAPI_BASE_URL does not match TON_NETWORK')
    return {'enabled': ton.is_configured(), 'network': network}


def ton_quote(user_id, plan, sender):
    from services import ton_payments as ton
    from tonsdk.utils import Address, InvalidAddressError
    config = ton_config()
    if not config['enabled']:
        raise ValueError('TON payments are disabled; use Stars')
    try:
        sender = Address(sender).to_string(False)
    except InvalidAddressError as exc:
        raise ValueError('Invalid sender address') from exc
    info = ton.payment_links(plan, int(user_id))
    try:
        Address(info['address'])  # fail before opening a wallet on invalid config
    except InvalidAddressError as exc:
        raise ValueError('Invalid payment wallet configuration') from exc
    return issue_ticket(user_id, plan, 'ton', info['memo'],
                        network=info['network'], address=info['address'], sender=sender,
                        amount=str(info['amount_nanoton']), memo=info['memo'],
                        valid_until=int(time.time()) + 300)


def stars_ticket(user_id, plan):
    from core.pricing import PLANS
    if plan not in PLANS:
        raise ValueError('Invalid plan')
    return issue_ticket(user_id, plan, 'stars', secrets.token_hex(16))


def invoice_payload(ticket):
    return f"premium_{ticket['plan']}|{ticket['reference']}|{ticket['user_id']}"


def parse_invoice(payload, user_id):
    """Legacy bot invoices stay valid; new miniapp invoices are payer-bound."""
    parts = payload.split('|')
    plan = parts[0].removeprefix('premium_')
    if len(parts) == 1:
        return plan, None
    if len(parts) != 3 or not re.fullmatch(r'[0-9a-f]{32}', parts[1]) or parts[2] != str(user_id):
        raise ValueError('Invoice belongs to another user or is malformed')
    return plan, parts[1]


async def checkout_status(ticket, message_hash=None):
    from services.engine_client import engine_client
    reference = ticket['reference']
    # Use the strict transport, not get_user_status()'s outage-as-Free fallback.
    result = await engine_client._get(
        'Checkout/status/' + quote(reference, safe=''),
        extra_headers={'X-Checkout-Assertion': engine_assertion(ticket['user_id'], reference)},
    )
    if not isinstance(result, dict) or result.get('status') not in ('pending', 'activated'):
        raise RuntimeError('Engine did not confirm checkout status')
    if result['status'] == 'activated' and not result.get('paymentId'):
        raise RuntimeError('Engine acknowledgement has no persisted payment')
    result = dict(result)
    # Chain lookup is informational only; it can NEVER cause activation.
    if ticket['rail'] == 'ton' and message_hash:
        if not re.fullmatch(r'[0-9a-fA-F]{64}', message_hash):
            raise ValueError('Expected a normalized message hash, not a BOC')
        base = 'https://testnet.tonapi.io/v2' if ticket['network'] == 'testnet' else 'https://tonapi.io/v2'
        key = os.getenv('TONAPI_KEY') or os.getenv('TON_API_KEY')
        headers = {'Authorization': f'Bearer {key}'} if key else {}
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(f'{base}/blockchain/messages/{message_hash}/transaction', headers=headers)
            if response.status_code == 404:
                return result
            response.raise_for_status()
            transaction = response.json()
            from tonsdk.utils import Address
            account = transaction.get('account', {}).get('address')
            if not account or Address(account).to_string(False) != ticket['sender']:
                raise ValueError('Transaction account differs from the quoted sender')
            tx_hash = transaction.get('hash', '')
            if not re.fullmatch(r'[0-9a-fA-F]{64}', tx_hash):
                raise ValueError('Chain response has no transaction hash')
            result['transaction_hash'] = tx_hash
        except (httpx.HTTPError, ValueError, TypeError):
            result['lookup_error'] = 'Transaction lookup unavailable; activation check remains authoritative'
    return result
