"""
services/ton_payments.py — TON on-chain payment engine (money-critical).

DESIGN (chosen for safety + solo-dev maintainability)
-----------------------------------------------------
Instead of a bespoke per-subscriber smart contract (high audit/deploy risk), the
live TON path is a DIRECT TRANSFER to ONE monitored wallet, tagged with a
unique, self-describing memo:

    TGP1-<telegram_user_id>-<plan_key>-<nonce>      e.g. TGP1-123456-pro_plus-9f3a1c

A background loop polls that wallet's incoming transfers via TONAPI. For each
transfer it:
    1. decodes the memo  -> (user_id, plan_key)
    2. validates the amount against the canonical price for that plan
    3. activates the subscription via the ATOMIC, idempotent Engine endpoint
       (engine_client.complete_payment), using the on-chain event id as the
       idempotency key — so a transfer can NEVER double-activate or be lost.

WHY THIS IS SAFE
----------------
* The memo is self-describing, so activation does NOT depend on Redis or any
  in-memory pending record. Even after a restart with an empty cache, the
  monitor can still fully process a payment from the on-chain comment alone.
* complete_payment is idempotent (Postgres unique index on external_id), so the
  monitor can reprocess the same transfer any number of times harmlessly.
* If the Engine is briefly down, the activation is hadned to the durable
  activation queue (services/activation_queue.py) and retried until it lands.
* Underpayments are rejected; overpayments still activate (user paid enough).

This module is deliberately free of aiogram imports so its logic is unit
testable. The Telegram UX lives in handlers/ton_payment_handler.py.
"""

from __future__ import annotations

import asyncio
import os
import secrets
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import structlog

from core.pricing import (
    PLANS,
    duration_days,
    expected_nanoton,
    is_valid_plan,
    plan_to_engine,
)

log = structlog.get_logger(__name__)

MEMO_PREFIX = "TGP1"


# --------------------------------------------------------------------------- #
# Configuration (read live from env so ops can flip flags without code changes)
# --------------------------------------------------------------------------- #
def is_enabled() -> bool:
    """TON payments are OFF by default until verified on testnet."""
    return os.getenv("TON_PAYMENTS_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def network() -> str:
    return os.getenv("TON_NETWORK", "testnet").strip().lower()


def is_testnet() -> bool:
    return network() != "mainnet"


def monitored_wallet() -> str:
    """The single wallet users send TON to. Empty => path disabled."""
    return os.getenv("MONITORED_WALLET_ADDRESS", "").strip()


def tolerance() -> float:
    try:
        return float(os.getenv("TON_PAYMENT_TOLERANCE", "0.02"))
    except ValueError:
        return 0.02


def monitor_interval() -> int:
    try:
        return int(os.getenv("TON_MONITOR_INTERVAL", "30"))
    except ValueError:
        return 30


def tonapi_base() -> str:
    if os.getenv("TONAPI_BASE_URL"):
        return os.getenv("TONAPI_BASE_URL").rstrip("/")
    return "https://testnet.tonapi.io/v2" if is_testnet() else "https://tonapi.io/v2"


def is_configured() -> bool:
    """True only when the path is enabled AND a wallet is set."""
    return is_enabled() and bool(monitored_wallet())


# --------------------------------------------------------------------------- #
# Pure helpers (memo + amount) — fully unit-testable
# --------------------------------------------------------------------------- #
def generate_memo(user_id: int, plan_key: str) -> str:
    """Build a unique, self-describing payment memo.

    Plan keys never contain '-' (e.g. 'pro_plus' uses '_'), so '-' is a safe
    delimiter. The nonce defends against accidental memo reuse.
    """
    if not is_valid_plan(plan_key):
        raise ValueError(f"unknown plan: {plan_key}")
    nonce = secrets.token_hex(3)  # 6 hex chars
    return f"{MEMO_PREFIX}-{int(user_id)}-{plan_key}-{nonce}"


def parse_memo(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Decode a memo back to {user_id, plan_key, nonce}, or None if invalid."""
    if not text:
        return None
    parts = text.strip().split("-")
    if len(parts) != 4:
        return None
    prefix, uid, plan, nonce = parts
    if prefix != MEMO_PREFIX or not uid.isdigit() or not is_valid_plan(plan) or not nonce.isalnum():
        return None
    return {"user_id": int(uid), "plan_key": plan, "nonce": nonce}


def validate_amount(received_nanoton: int, plan_key: str, tol: Optional[float] = None) -> bool:
    """True if the received amount covers the tier price (within tolerance)."""
    exp = expected_nanoton(plan_key)
    if exp is None:
        return False
    t = tolerance() if tol is None else tol
    return int(received_nanoton) >= int(exp * (1 - t))


def payment_links(plan_key: str, user_id: int) -> Dict[str, Any]:
    """Build everything the UI needs to show a payment request."""
    exp = expected_nanoton(plan_key)
    memo = generate_memo(user_id, plan_key)
    addr = monitored_wallet()
    enc = quote(memo, safe="")
    return {
        "address": addr,
        "plan_key": plan_key,
        "plan_name": PLANS[plan_key]["name"],
        "amount_ton": PLANS[plan_key]["price_ton"],
        "amount_nanoton": exp,
        "memo": memo,
        "ton_deeplink": f"ton://transfer/{addr}?amount={exp}&text={enc}",
        "tonkeeper_link": f"https://app.tonkeeper.com/transfer/{addr}?amount={exp}&text={enc}",
        "network": network(),
    }


# --------------------------------------------------------------------------- #
# Best-effort pending store (Redis) — for UX/status only, NOT for correctness
# --------------------------------------------------------------------------- #
def _redis():
    try:
        from utils.redis_conn import redis_client
        return redis_client
    except Exception:
        return None


def store_pending(user_id: int, plan_key: str, memo: str) -> None:
    r = _redis()
    if not r:
        return
    try:
        import json
        ttl = int(os.getenv("TON_PAYMENT_EXPIRY_MIN", "60")) * 60
        r.set(f"ton_pending:{user_id}", json.dumps({"plan_key": plan_key, "memo": memo}), ex=ttl)
    except Exception as e:
        log.debug("ton_pending_store_failed", err=str(e))


def get_pending(user_id: int) -> Optional[Dict[str, Any]]:
    r = _redis()
    if not r:
        return None
    try:
        import json
        raw = r.get(f"ton_pending:{user_id}")
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _already_processed(external_id: str) -> bool:
    r = _redis()
    if not r:
        return False
    try:
        return bool(r.exists(f"ton_done:{external_id}"))
    except Exception:
        return False


def _mark_processed(external_id: str) -> None:
    r = _redis()
    if not r:
        return
    try:
        r.set(f"ton_done:{external_id}", "1", ex=7 * 86400)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Activation (reuses the atomic, idempotent Engine endpoint + durable queue)
# --------------------------------------------------------------------------- #
async def activate_from_payment(
    user_id: int, plan_key: str, external_id: str, amount_nanoton: int
) -> str:
    """Activate via Postgres (atomic/idempotent). Returns a status string:

        "activated" | "already" | "queued" | "failed"
    """
    from services.engine_client import engine_client

    res = await engine_client.complete_payment(
        telegram_id=user_id,
        plan=plan_to_engine(plan_key),
        provider="ton",
        external_id=external_id,
        duration_days=duration_days(plan_key),
        amount_ton=amount_nanoton / 1e9,
    )

    if res.get("ok"):
        if res.get("already_processed"):
            return "already"
        await _notify_user(user_id, plan_key)
        log.info("ton_payment_activated", user_id=user_id, plan=plan_key, external_id=external_id)
        return "activated"

    if res.get("permanent"):
        log.error(
            "ton_payment_permanent_failure",
            user_id=user_id, plan=plan_key, external_id=external_id,
            error=res.get("error"), message=res.get("message"),
        )
        return "failed"

    # Transient (Engine/network down) -> durable queue, retried until it lands.
    try:
        from services.activation_queue import enqueue
        await enqueue({
            "user_id": user_id,
            "plan": plan_to_engine(plan_key),
            "provider": "ton",
            "external_id": external_id,
            "duration_days": duration_days(plan_key),
            "plan_key": plan_key,
        })
        log.warning("ton_payment_queued", user_id=user_id, plan=plan_key, external_id=external_id)
        return "queued"
    except Exception as e:
        log.critical(
            "TON_ACTIVATION_LOST_RISK",
            user_id=user_id, plan=plan_key, external_id=external_id, err=str(e),
        )
        return "failed"


async def _notify_user(user_id: int, plan_key: str) -> None:
    try:
        from core.bot_instance import get_bot
        bot = get_bot()
        if not bot:
            return
        name = PLANS.get(plan_key, {}).get("name", "Premium")
        await bot.send_message(
            user_id,
            f"✅ <b>TON payment confirmed!</b>\n\n"
            f"Your <b>{name}</b> is now active. Thank you for supporting TonGPT 🚀",
            parse_mode="HTML",
        )
    except Exception as e:  # noqa: BLE001
        log.debug("ton_notify_failed", err=str(e), user_id=user_id)


# --------------------------------------------------------------------------- #
# On-chain monitoring (TONAPI). httpx imported lazily so tests don't need it.
# --------------------------------------------------------------------------- #
async def fetch_incoming_events(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch recent events for the monitored wallet. Returns [] on any error."""
    import httpx

    addr = monitored_wallet()
    if not addr:
        return []
    url = f"{tonapi_base()}/accounts/{addr}/events"
    headers = {"Accept": "application/json", "User-Agent": "TonGPT-Bot/1.0"}
    api_key = os.getenv("TONAPI_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params={"limit": limit}, headers=headers)
            resp.raise_for_status()
            return resp.json().get("events", []) or []
    except Exception as e:  # noqa: BLE001
        log.warning("ton_fetch_events_failed", err=str(e))
        return []


def extract_transfers(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pull successful incoming TonTransfers (with comments) from TONAPI events.

    Defensive about response shape — TONAPI nests the transfer under either
    'TonTransfer' or 'tonTransfer'. Unknown shapes are skipped (and logged by
    the caller), never crash the monitor.
    """
    out: List[Dict[str, Any]] = []
    for ev in events:
        event_id = ev.get("event_id") or ev.get("eventId")
        for action in ev.get("actions", []) or []:
            if (action.get("type") or "").lower() != "tontransfer":
                continue
            status = (action.get("status") or "ok").lower()
            if status not in ("ok", ""):
                continue
            tt = action.get("TonTransfer") or action.get("tonTransfer") or {}
            comment = tt.get("comment")
            amount = tt.get("amount")
            if comment is None or amount is None:
                continue
            out.append({"event_id": event_id, "comment": comment, "amount": amount})
    return out


async def process_events_once() -> int:
    """Single monitoring pass. Returns the number of NEW activations."""
    if not is_configured():
        return 0

    events = await fetch_incoming_events()
    transfers = extract_transfers(events)
    activated = 0

    for tr in transfers:
        event_id = tr["event_id"]
        if not event_id:
            continue
        external_id = f"ton:{event_id}"
        if _already_processed(external_id):
            continue

        parsed = parse_memo(tr["comment"])
        if not parsed:
            continue  # not one of our payments

        try:
            amount_nanoton = int(tr["amount"])
        except (TypeError, ValueError):
            continue

        if not validate_amount(amount_nanoton, parsed["plan_key"]):
            log.warning(
                "ton_payment_underpaid",
                user_id=parsed["user_id"], plan=parsed["plan_key"],
                received=amount_nanoton, expected=expected_nanoton(parsed["plan_key"]),
                external_id=external_id,
            )
            # Mark processed so we don't keep re-evaluating; the user must re-pay.
            _mark_processed(external_id)
            continue

        status = await activate_from_payment(
            parsed["user_id"], parsed["plan_key"], external_id, amount_nanoton
        )
        if status in ("activated", "already", "queued"):
            _mark_processed(external_id)  # queue owns it now if "queued"
        if status == "activated":
            activated += 1

    return activated


async def monitor_loop(interval: Optional[int] = None) -> None:
    """Background task: poll the monitored wallet and activate paid subscriptions."""
    if not is_enabled():
        log.info("ton_monitor_disabled", reason="TON_PAYMENTS_ENABLED is false")
        return
    if not monitored_wallet():
        log.warning("ton_monitor_no_wallet", reason="MONITORED_WALLET_ADDRESS not set")
        return

    interval = interval or monitor_interval()
    log.info("ton_monitor_started", wallet=monitored_wallet()[:8] + "…", network=network(), interval=interval)
    while True:
        try:
            n = await process_events_once()
            if n:
                log.info("ton_monitor_activated", count=n)
        except Exception as e:  # noqa: BLE001
            log.error("ton_monitor_error", err=str(e))
        await asyncio.sleep(interval)


__all__ = [
    "MEMO_PREFIX",
    "is_enabled", "is_configured", "network", "is_testnet", "monitored_wallet",
    "tolerance", "monitor_interval", "tonapi_base",
    "generate_memo", "parse_memo", "validate_amount", "payment_links",
    "store_pending", "get_pending",
    "activate_from_payment", "fetch_incoming_events", "extract_transfers",
    "process_events_once", "monitor_loop",
]
