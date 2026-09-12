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
       idempotency key, preserving deduplication when a scan is replayed.

WHY THIS IS SAFE
----------------
* The memo is self-describing, so activation does NOT depend on Redis or any
  in-memory pending record. Even after a restart with an empty cache, the
  monitor can still fully process a payment from the on-chain comment alone.
* complete_payment is idempotent (Postgres unique index on external_id), so the
  monitor can reprocess the same transfer any number of times harmlessly.
* If the Engine is briefly down, the activation is handed to the shared
  activation queue (services/activation_queue.py). The chain checkpoint stays
  behind that payment until the Engine confirms a persisted payment record.
* Underpayments are rejected; overpayments still activate (user paid enough).

This module is deliberately free of aiogram imports so its logic is unit
testable. The Telegram UX lives in handlers/ton_payment_handler.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import structlog
from tonsdk.utils import Address, InvalidAddressError

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
    """The single wallet users send TON to. Empty => path disabled.

    CFG-DRIFT-001: main.py requires PAYMENT_WALLET_ADDRESS, so accept that as a
    fallback — setting the one required var now also configures the monitor
    (previously this read only MONITORED_WALLET_ADDRESS and silently stayed off).
    """
    return (os.getenv("MONITORED_WALLET_ADDRESS")
            or os.getenv("PAYMENT_WALLET_ADDRESS")
            or "").strip()


def tolerance() -> float:
    """Underpayment tolerance, clamped to a safe band (PAY-009).

    A misconfigured env (e.g. TON_PAYMENT_TOLERANCE=1.0) previously meant
    "accept zero TON". Clamped to [0, 0.02]: at most a 2% shortfall is ever
    accepted, and a negative value can't reject exact payments. Out-of-band
    values are logged loudly so the misconfig is visible.
    """
    _MAX_TOL = 0.02
    try:
        raw = float(os.getenv("TON_PAYMENT_TOLERANCE", "0.02"))
    except ValueError:
        return _MAX_TOL
    clamped = min(max(raw, 0.0), _MAX_TOL)
    if raw != clamped:
        log.error("ton_payment_tolerance_out_of_band", configured=raw, clamped_to=clamped)
    return clamped


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
        # An acknowledgement without a persisted payment is not commit proof.
        # In particular, the Engine can currently return AlreadyProcessed/null.
        if not res.get("payment_id"):
            log.error("ton_payment_unconfirmed_ack", external_id=external_id)
            return "failed"
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
            # Carry the paid amount so the queue drain passes the Engine's amount
            "amount_ton": amount_nanoton / 1e9,  # validation (PAY-001).
        })
        log.warning("ton_payment_queued", user_id=user_id, plan=plan_key, external_id=external_id)
        return "queued"
    except Exception as e:
        log.critical(
            "TON_ACTIVATION_LOST_RISK",
            user_id=user_id, plan=plan_key, external_id=external_id, err=str(e),
        )
        return "failed"


async def _notify_underpaid(user_id: int, plan_key: str, received_nanoton: int) -> None:
    """Best-effort notice when a TON transfer is below the plan price (PAY-010).
    The funds are received but no subscription is granted, so the user MUST be
    told rather than left wondering."""
    try:
        from core.bot_instance import get_bot
        bot = get_bot()
        if not bot:
            return
        name = PLANS.get(plan_key, {}).get("name", "your plan")
        expected = expected_nanoton(plan_key) or 0
        await bot.send_message(
            user_id,
            f"⚠️ <b>Payment received but underpaid</b>\n\n"
            f"We received <b>{received_nanoton / 1e9:.4f} TON</b> for <b>{name}</b>, but it "
            f"requires at least <b>{expected / 1e9:.2f} TON</b>. Your subscription was "
            f"<b>NOT</b> activated.\n\n"
            f"Please send the correct amount with the exact memo, or contact "
            f"@TonGPT_Support to recover this payment.",
            parse_mode="HTML",
        )
    except Exception as e:  # noqa: BLE001
        log.debug("ton_underpaid_notify_failed", err=str(e), user_id=user_id)


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
async def fetch_incoming_events(limit: int = 50, before_lt: Optional[int] = None) -> List[Dict[str, Any]]:
    """Fetch a page of events for the monitored wallet (newest first).

    ``before_lt`` pages backwards: TONAPI returns events with lt < before_lt, so
    passing the oldest lt of the previous page yields the next older page.
    Errors raise: a failed request must never be mistaken for end of history.
    """
    import httpx

    addr = monitored_wallet()
    if not addr:
        return []
    url = f"{tonapi_base()}/accounts/{addr}/events"
    headers = {"Accept": "application/json", "User-Agent": "TonGPT-Bot/1.0"}
    api_key = os.getenv("TONAPI_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    params: Dict[str, Any] = {"limit": limit}
    if before_lt is not None:
        params["before_lt"] = int(before_lt)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
            events = payload.get("events") if isinstance(payload, dict) else None
            if not isinstance(events, list) or any(not isinstance(ev, dict) for ev in events):
                raise ValueError("Invalid TONAPI events response")
            _note_fetch_ok()
            return events
    except Exception as e:  # noqa: BLE001
        log.warning("ton_fetch_events_failed", err=str(e))
        await _note_fetch_failure(e)
        raise


# REL-001: a sustained TONAPI outage used to stall activations silently ([] on
# every error, warning-level log only). Track consecutive failures and escalate
# through error_reporter once past a threshold, then back off (re-alert every
# N further failures) so ops hears about an outage without being spammed.
_FETCH_FAIL_ALERT_AFTER = int(os.getenv("TON_FETCH_FAIL_ALERT_AFTER", "10"))
_consecutive_fetch_failures = 0


def _note_fetch_ok() -> None:
    global _consecutive_fetch_failures
    if _consecutive_fetch_failures >= _FETCH_FAIL_ALERT_AFTER:
        log.info("ton_fetch_recovered", after_failures=_consecutive_fetch_failures)
    _consecutive_fetch_failures = 0


async def _note_fetch_failure(err: Exception) -> None:
    global _consecutive_fetch_failures
    _consecutive_fetch_failures += 1
    n = _consecutive_fetch_failures
    if n >= _FETCH_FAIL_ALERT_AFTER and n % _FETCH_FAIL_ALERT_AFTER == 0:
        log.error("ton_fetch_outage", consecutive_failures=n, err=str(err))
        try:
            from services.error_reporter import error_reporter
            await error_reporter.report(
                Exception(f"TONAPI outage: {n} consecutive event-fetch failures "
                          f"(payment monitor is blind): {err}"),
                context="ton_payments.fetch_incoming_events",
            )
        except Exception as rep_err:  # noqa: BLE001
            log.debug("ton_fetch_outage_report_failed", err=str(rep_err))


# This is a replay optimization, written only after the WHOLE range is confirmed.
# Do not trust the old global key: it could cover failed/queued payments and did
# not identify its wallet/network. A new namespace deliberately replays history
# through the unchanged Engine idempotency keys; no payment IDs are migrated here.
def _checkpoint_key() -> str:
    source = "\n".join((Address(monitored_wallet()).to_string(False), network(), tonapi_base()))
    return "ton_monitor_confirmed_lt:v2:" + hashlib.sha256(source.encode()).hexdigest()


def _get_high_water_lt(key: Optional[str] = None) -> Optional[int]:
    key = key or _checkpoint_key()
    r = _redis()
    if not r:
        return None
    try:
        v = r.get(key)
        return int(v) if v and int(v) > 0 else None
    except Exception:
        return None


def _set_high_water_lt(lt: int, key: Optional[str] = None) -> bool:
    key = key or _checkpoint_key()
    r = _redis()
    try:
        if r and r.set(key, str(int(lt))):
            return True
        log.error("ton_checkpoint_write_failed", lt=lt, err="Redis did not acknowledge the write")
    except Exception as e:
        log.error("ton_checkpoint_write_failed", lt=lt, err=str(e))
    return False


def _event_lt(ev: Dict[str, Any]) -> Optional[int]:
    try:
        lt = ev.get("lt")
        return int(lt) if lt is not None else None
    except (TypeError, ValueError):
        return None


def extract_transfers(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pull successful incoming TonTransfers (with comments) from TONAPI events.

    Defensive about response shape — TONAPI nests the transfer under either
    'TonTransfer' or 'tonTransfer'. Unknown shapes are skipped (and logged by
    the caller), never crash the monitor.

    Invalid monitored-wallet configuration raises before processing any event.
    """
    # Compare the workchain AND account hash, independently of display flags.
    # Let invalid configuration stop the poll rather than silently skip payments.
    expected_recipient = Address(monitored_wallet()).to_string(False)
    out: List[Dict[str, Any]] = []
    for ev in events:
        event_id = ev.get("event_id") or ev.get("eventId")
        lt = _event_lt(ev)
        # ``idx`` is the action's position within the event. One event can carry
        # MULTIPLE TonTransfers (e.g. batched), so the per-transfer idempotency
        # key MUST include it — keying on event_id alone merged/lost a second
        # payer's transfer (PAY-004).
        for idx, action in enumerate(ev.get("actions", []) or []):
            if (action.get("type") or "").lower() != "tontransfer":
                continue
            status = (action.get("status") or "ok").lower()
            if status not in ("ok", ""):
                continue
            tt = action.get("TonTransfer") or action.get("tonTransfer") or {}
            if not isinstance(tt, dict):
                continue
            recipient = tt.get("recipient")
            if not isinstance(recipient, dict) or not isinstance(recipient.get("address"), str):
                continue
            try:
                actual_recipient = Address(recipient["address"]).to_string(False)
            except (InvalidAddressError, ValueError):
                continue
            if actual_recipient != expected_recipient:
                continue
            comment = tt.get("comment")
            amount = tt.get("amount")
            if comment is None or amount is None:
                continue
            out.append({"event_id": event_id, "idx": idx, "lt": lt, "comment": comment, "amount": amount})
    return out


async def _process_one_event(ev: Dict[str, Any]) -> tuple[int, bool]:
    """Return (new activations, all matching payments confirmed by the Engine)."""
    activated = 0
    for tr in extract_transfers([ev]):
        parsed = parse_memo(tr["comment"])
        if not parsed:
            continue  # not one of our payments
        event_id = tr["event_id"]
        if not event_id:
            raise ValueError("TON payment event has no idempotency identifier")
        # Per-transfer idempotency key (PAY-004): event_id + action index.
        external_id = f"ton:{event_id}:{tr['idx']}"
        try:
            amount_nanoton = int(tr["amount"])
        except (TypeError, ValueError) as e:
            raise ValueError("TON payment has an invalid amount") from e

        if not validate_amount(amount_nanoton, parsed["plan_key"]):
            log.warning(
                "ton_payment_underpaid",
                user_id=parsed["user_id"], plan=parsed["plan_key"],
                received=amount_nanoton, expected=expected_nanoton(parsed["plan_key"]),
                external_id=external_id,
            )
            # PAY-010: tell the user so an underpayment isn't silently swallowed.
            if not _already_processed(external_id):
                await _notify_underpaid(parsed["user_id"], parsed["plan_key"], amount_nanoton)
                _mark_processed(external_id)  # notification suppression only
            continue

        status = await activate_from_payment(
            parsed["user_id"], parsed["plan_key"], external_id, amount_nanoton
        )
        # Legacy ton_done markers include queued payments. Always ask the Engine
        # about paid transfers; neither the cache nor the shared queue proves a
        # payment was committed (the queue's torn-tail issue is a separate fix).
        if status not in ("activated", "already"):
            log.warning("ton_checkpoint_blocked", external_id=external_id, status=status)
            return activated, False
        if status == "activated":
            activated += 1
    return activated, True


@dataclass
class _ScanProgress:
    key: str
    high_water: Optional[int]
    newest_lt: Optional[int] = None
    before_lt: Optional[int] = None


# A page budget yields work to the next poll, without claiming completion.
# Losing this cursor on restart is safe: the last committed checkpoint remains
# behind the gap, and the Engine deduplicates replayed activations.
_scan_progress: Optional[_ScanProgress] = None
_scan_lock = asyncio.Lock()


async def process_events_once() -> int:
    """Process a bounded chunk; checkpoint only a completely confirmed range."""
    async with _scan_lock:
        return await _process_events_once()


async def _process_events_once() -> int:
    global _scan_progress
    if not is_configured():
        return 0

    page_limit = 50
    max_pages = max(1, int(os.getenv("TON_MONITOR_MAX_PAGES", "10")))
    key = _checkpoint_key()  # validate the configured wallet even on empty polls
    high_water = _get_high_water_lt(key)
    if (_scan_progress is None or _scan_progress.key != key
            or _scan_progress.high_water != high_water):
        _scan_progress = _ScanProgress(key, high_water)
    scan = _scan_progress

    activated = 0
    complete = False

    for _page in range(max_pages):
        events = await fetch_incoming_events(limit=page_limit, before_lt=scan.before_lt)
        if not events:
            complete = True
            break

        # Validate the whole page before activation or cursor movement. An
        # invalid/non-descending LT cannot safely define the remaining range.
        previous_lt = scan.before_lt
        for ev in events:
            lt = _event_lt(ev)
            if lt is None or lt <= 0 or (previous_lt is not None and lt >= previous_lt):
                raise ValueError("Invalid or non-descending TONAPI event cursor")
            previous_lt = lt
        if scan.newest_lt is None:
            scan.newest_lt = _event_lt(events[0])

        for ev in events:
            ev_lt = _event_lt(ev)
            if high_water is not None and ev_lt <= high_water:
                complete = True
                break
            if ev.get("in_progress"):
                log.warning("ton_checkpoint_blocked", lt=ev_lt, status="in_progress")
                return activated
            count, confirmed = await _process_one_event(ev)
            activated += count
            if not confirmed:
                return activated  # retry this page; never skip the failed event

        if complete:
            break
        scan.before_lt = previous_lt
        # Only an explicit empty page (or the old checkpoint) establishes the
        # end. A short page alone does not prove that pagination is complete.

    if complete:
        if scan.newest_lt is not None and (high_water is None or scan.newest_lt > high_water):
            _set_high_water_lt(scan.newest_lt, key)
        # If Redis failed, the next scan replays from the last saved checkpoint.
        _scan_progress = None
    else:
        log.info("ton_scan_yielded", before_lt=scan.before_lt, checkpoint=high_water)
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
