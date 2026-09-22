"""
services/activation_queue.py — durable fallback for subscription activation.

WHY
---
The happy path is: Telegram Stars payment succeeds -> we call
``engine_client.complete_payment`` which records + activates the subscription in
Postgres atomically. But the C# Engine (or the network) can be briefly down at
exactly that moment. We must NEVER lose a paid activation.

This module is the safety net. When a synchronous activation fails for a
transient reason, the payment is written to a small append-only file on local
disk (NOT Redis — Redis may itself be down, which is the whole point). A
background loop then retries each pending activation until Postgres confirms it.

Because ``complete_payment`` is idempotent (keyed by the Telegram charge id via a
unique DB index), retrying is always safe: a duplicate simply returns
``already_processed=True`` and never double-grants a subscription.

The queue file format is JSON-lines (one JSON object per line) so it is:
  * append-only and crash-safe (a partial last line is just skipped),
  * human-readable for ops/debugging,
  * trivially survives process restarts.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, List

import structlog

log = structlog.get_logger(__name__)

# Local durable store. Lives under data/ which already exists in the repo.
QUEUE_FILE = os.getenv("ACTIVATION_QUEUE_FILE", os.path.join("data", "pending_activations.jsonl"))
RETRY_INTERVAL = int(os.getenv("ACTIVATION_RETRY_INTERVAL", "60"))   # seconds between drains
ALERT_AFTER_ATTEMPTS = int(os.getenv("ACTIVATION_ALERT_AFTER", "10"))  # escalate after N failures
# QUEUE-001: poison items no longer retry forever. After this many attempts the
# item is moved to a dead-letter file for manual ops review (money is never
# deleted — just parked where it can't clog the live queue).
DEAD_LETTER_AFTER = int(os.getenv("ACTIVATION_DEAD_LETTER_AFTER", "120"))
DEAD_LETTER_FILE = os.getenv(
    "ACTIVATION_DEAD_LETTER_FILE", os.path.join("data", "dead_activations.jsonl")
)

# Serializes all reads/writes of the queue file within this process.
_lock = asyncio.Lock()


# --------------------------------------------------------------------------- #
# Low-level file helpers (run via asyncio.to_thread so we never block the loop)
# --------------------------------------------------------------------------- #
def _ensure_dir() -> None:
    d = os.path.dirname(QUEUE_FILE)
    if d:
        os.makedirs(d, exist_ok=True)


def _append(item: Dict[str, Any]) -> None:
    _ensure_dir()
    with open(QUEUE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())  # durability across power loss / restart


def _read_all() -> List[Dict[str, Any]]:
    if not os.path.exists(QUEUE_FILE):
        return []
    items: List[Dict[str, Any]] = []
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip a torn/partial line rather than losing the whole queue.
                log.warning("activation_queue_bad_line", line=line[:120])
    return items


def _append_dead_letter(item: Dict[str, Any]) -> None:
    """Persist a poison item to the dead-letter file (QUEUE-001)."""
    d = os.path.dirname(DEAD_LETTER_FILE)
    if d:
        os.makedirs(d, exist_ok=True)
    item = dict(item)
    item["dead_lettered_at"] = time.time()
    with open(DEAD_LETTER_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _write_all(items: List[Dict[str, Any]]) -> None:
    _ensure_dir()
    tmp = QUEUE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, QUEUE_FILE)  # atomic swap


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
async def enqueue(item: Dict[str, Any]) -> None:
    """Persist a pending activation. Required keys: user_id, plan, external_id.

    Optional: provider, duration_days, amount_ton, plan_key.
    """
    record = {
        "user_id": item["user_id"],
        "plan": item["plan"],                       # engine plan name (Starter/Pro/...)
        "provider": item.get("provider", "telegram_stars"),
        "external_id": item["external_id"],
        "duration_days": int(item.get("duration_days", 30)),
        "amount_ton": float(item.get("amount_ton", 0.0)),
        "amount_stars": int(item.get("amount_stars", 0)),  # needed for Engine amount check
        "plan_key": item.get("plan_key"),
        "enqueued_at": time.time(),
        "attempts": int(item.get("attempts", 0)),
        **({'checkout_reference': item['checkout_reference']} if item.get('checkout_reference') else {}),
        **({k: item.get(k) for k in ('quote_reference', 'paid_units', 'paid_at')} if item.get('quote_reference') else {}),
    }
    async with _lock:
        await asyncio.to_thread(_append, record)
    log.warning(
        "activation_queued",
        user_id=record["user_id"], plan=record["plan"], external_id=record["external_id"],
    )


async def pending_count() -> int:
    async with _lock:
        items = await asyncio.to_thread(_read_all)
    return len(items)


async def drain_once() -> int:
    """Attempt every pending activation once. Returns the number activated.

    Idempotency makes this safe even if an item is processed more than once.
    """
    from services.engine_client import engine_client

    async with _lock:
        items = await asyncio.to_thread(_read_all)

    if not items:
        return 0

    # QUEUE-002: dedupe the batch on external_id so a double-enqueued payment
    # only produces one activation attempt (and one user notification).
    seen_ids: set = set()
    deduped: List[Dict[str, Any]] = []
    for it in items:
        ext = it.get("external_id")
        if ext in seen_ids:
            continue
        seen_ids.add(ext)
        deduped.append(it)
    items = deduped

    activated = 0
    still_pending: List[Dict[str, Any]] = []

    for it in items:
        try:
            res = await engine_client.complete_payment(
                telegram_id=it["user_id"],
                plan=it["plan"],
                provider=it.get("provider", "telegram_stars"),
                external_id=it["external_id"],
                duration_days=it.get("duration_days", 30),
                amount_ton=it.get("amount_ton", 0.0),
                amount_stars=it.get("amount_stars", 0),
                **({'checkout_reference': it['checkout_reference']} if it.get('checkout_reference') else {}),
                **({k: it.get(k) for k in ('quote_reference', 'paid_units', 'paid_at')} if it.get('quote_reference') else {}),
            )
        except Exception as e:  # never let one bad item stop the drain
            res = {"ok": False, "error": str(e), "permanent": False}

        if res.get("ok"):
            if not res.get('scheduled'):
                activated += 1
            it['scheduled'] = bool(res.get('scheduled'))
            log.info(
                "activation_reconciled",
                user_id=it["user_id"], plan=it["plan"], external_id=it["external_id"],
                already=res.get("already_processed"),
            )
            await _notify_user(it)
        elif res.get('held') and res.get('payment_id'):
            # The receipt is now durably held in PostgreSQL, not activated.
            log.warning('payment_reconciliation_required', payment_id=res['payment_id'], external_id=it['external_id'])
            await _alert(it, reason='reconciliation_required')
        elif res.get("permanent") and not it.get('quote_reference'):
            # e.g. invalid plan — retrying will never help. Drop it but shout.
            log.error(
                "activation_dropped_permanent",
                item=it, error=res.get("error"), message=res.get("message"),
            )
            await _alert(it, reason="permanent_failure")
        else:
            it["attempts"] = int(it.get("attempts", 0)) + 1
            # QUEUE-001: ">=" + modulo so the alert can't be skipped by a
            # double-increment and re-fires periodically during a long outage
            # (once per ALERT_AFTER_ATTEMPTS further failures, not just once).
            if (it["attempts"] >= ALERT_AFTER_ATTEMPTS
                    and it["attempts"] % ALERT_AFTER_ATTEMPTS == 0):
                log.error("activation_retry_threshold_reached", item=it)
                await _alert(it, reason="retry_threshold")
            if it["attempts"] >= DEAD_LETTER_AFTER:
                # Poison item: park it in the dead-letter file for manual
                # review instead of retrying forever (QUEUE-001).
                log.error("activation_dead_lettered", item=it)
                await _alert(it, reason="dead_letter")
                try:
                    await asyncio.to_thread(_append_dead_letter, it)
                except Exception as dl_err:  # noqa: BLE001
                    # Could not persist to dead-letter — keep it in the live
                    # queue rather than silently dropping a paid activation.
                    log.error("activation_dead_letter_write_failed", err=str(dl_err))
                    still_pending.append(it)
            else:
                still_pending.append(it)

    # Rewrite the queue: keep still-pending items + anything enqueued during the
    # drain (identified by external_id not in the batch we just handled).
    async with _lock:
        current = await asyncio.to_thread(_read_all)
        handled_ids = {i["external_id"] for i in items}
        added_during = [c for c in current if c.get("external_id") not in handled_ids]
        await asyncio.to_thread(_write_all, still_pending + added_during)

    return activated


async def reconciliation_loop(interval: int | None = None) -> None:
    """Background task: periodically drain the pending-activation queue."""
    interval = interval or RETRY_INTERVAL
    log.info("activation_reconciliation_started", interval=interval, file=QUEUE_FILE)
    while True:
        try:
            n = await drain_once()
            if n:
                log.info("activation_drain_complete", activated=n)
        except Exception as e:
            log.error("activation_drain_error", err=str(e))
        await asyncio.sleep(interval)


# --------------------------------------------------------------------------- #
# Best-effort user notification + ops alert (never raise)
# --------------------------------------------------------------------------- #
async def _notify_user(item: Dict[str, Any]) -> None:
    try:
        from core.bot_instance import get_bot
        bot = get_bot()
        if not bot:
            return
        plan_label = (item.get("plan_key") or item.get("plan") or "premium").replace("_", " ").title()
        if item.get('scheduled'):
            await bot.send_message(item['user_id'], f"Your prepaid {plan_label} downgrade is recorded. Current paid coverage is preserved. Check the miniapp for the schedule.")
            return
        await bot.send_message(
            item["user_id"],
            f"✅ <b>Your {plan_label} is now active!</b>\n\n"
            "Thanks for your patience — your earlier payment has been fully applied.",
            parse_mode="HTML",
        )
    except Exception as e:  # noqa: BLE001
        log.debug("activation_notify_failed", err=str(e), user_id=item.get("user_id"))


async def _alert(item: Dict[str, Any], reason: str) -> None:
    try:
        from services.error_reporter import error_reporter
        await error_reporter.report(
            Exception(f"activation {reason}: user={item.get('user_id')} "
                      f"plan={item.get('plan')} ext={item.get('external_id')} "
                      f"attempts={item.get('attempts')}"),
            context="activation_queue",
            user_id=item.get("user_id"),
        )
    except Exception as e:  # noqa: BLE001
        log.debug("activation_alert_failed", err=str(e))


__all__ = ["enqueue", "drain_once", "reconciliation_loop", "pending_count", "QUEUE_FILE"]
