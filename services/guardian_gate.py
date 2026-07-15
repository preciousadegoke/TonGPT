# services/guardian_gate.py
"""
Guardian Gate — SPEC-002 Phase 1. The pre-trade safety oracle for machines.

TON Agentic Wallets give AI agents budgeted wallets but no token due diligence.
This module answers ONE question, machine-readably, before an agent trades:
"should this buy proceed?" — with calibrated semantics inherited from the
verdict engine:

  * `block` — high risk, OR unknown/unindexed ("no data is itself a signal";
    the gate defaults agents to fail-closed).
  * `warn`  — medium risk, OR data degraded (stale market feeds).
  * `pass`  — no major risk signals detected. NEVER means "safe": the response
    carries the historically observed false-negative rate with its denominator.

Every check produces a `gate_check` receipt: hashed, ledgered, graded by the
existing outcome tracker (was the token we blocked/passed later a rug?) and
Merkle-anchored daily — so TonGPT can eventually publish "N agent trades
screened, M blocked, K confirmed rugs" as an accountable record.

The gate is read-only over existing services: no new money paths, no keys.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from typing import Any, Dict, Optional, Tuple

import structlog

from services.outcome_tracker import LEDGER_FILE, canonical_hash

log = structlog.get_logger(__name__)

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
# v1 auth: GUARDIAN_API_KEYS="alice:supersecret1,bob:supersecret2"
# (per-key table + paid tiers are explicitly out of Phase-1 scope, spec §3.3)
_KEYS_ENV = "GUARDIAN_API_KEYS"
FREE_CHECKS_PER_DAY = int(os.getenv("GUARDIAN_FREE_PER_DAY", "200"))
CACHE_TTL = int(os.getenv("GUARDIAN_CACHE_TTL", "60"))            # per-token, s
STATS_TTL = int(os.getenv("GUARDIAN_STATS_TTL", "300"))           # track record, s
METHODOLOGY_URL = os.getenv(
    "GUARDIAN_METHODOLOGY_URL",
    "https://github.com/tongpt/tongpt/blob/main/docs/METHODOLOGY.md",
)

_now = time.time


def set_clock(fn) -> None:
    """Test hook. None restores time.time."""
    global _now
    _now = fn or time.time


# Friendly (EQ/UQ/kQ/0Q + 46 base64url chars) or raw (wc:64hex) TON address.
_ADDR_FRIENDLY = re.compile(r"^(?:EQ|UQ|kQ|0Q)[A-Za-z0-9_-]{46}$")
_ADDR_RAW = re.compile(r"^-?\d:[0-9a-fA-F]{64}$")


def is_valid_address(addr: str) -> bool:
    a = (addr or "").strip()
    return bool(_ADDR_FRIENDLY.match(a) or _ADDR_RAW.match(a))


# --------------------------------------------------------------------------- #
# Auth + per-key daily quota (v1: in-process; documented limitation)
# --------------------------------------------------------------------------- #
def _keyring() -> Dict[str, str]:
    """{api_key: caller_name} parsed from env at call time (rotatable)."""
    out: Dict[str, str] = {}
    for pair in (os.getenv(_KEYS_ENV) or "").split(","):
        pair = pair.strip()
        if ":" in pair:
            name, key = pair.split(":", 1)
            if name.strip() and len(key.strip()) >= 16:
                out[key.strip()] = name.strip()
            elif key.strip():
                log.warning("guardian_key_too_short", caller=name.strip())
    return out


_quota: Dict[str, Tuple[int, int]] = {}   # caller -> (day_index, used)


def authenticate(api_key: Optional[str]) -> Optional[str]:
    """Returns the caller name for a valid key, else None."""
    if not api_key:
        return None
    return _keyring().get(api_key.strip())


def consume_quota(caller: str) -> bool:
    """One check against the caller's daily allowance. In-process only (v1):
    restarts reset counters — acceptable for the free tier, documented."""
    day = int(_now() // 86400)
    d, used = _quota.get(caller, (day, 0))
    if d != day:
        d, used = day, 0
    if used >= FREE_CHECKS_PER_DAY:
        _quota[caller] = (d, used)
        return False
    _quota[caller] = (d, used + 1)
    return True


# --------------------------------------------------------------------------- #
# Track-record snippet (cached) — the trust collateral shipped in-band
# --------------------------------------------------------------------------- #
_stats_cache: Dict[str, Any] = {"ts": 0.0, "stats": None}


async def _stats() -> Optional[Dict[str, Any]]:
    now = _now()
    if _stats_cache["stats"] is not None and now - _stats_cache["ts"] < STATS_TTL:
        return _stats_cache["stats"]
    try:
        from services.outcome_tracker import track_record_stats
        st = await track_record_stats()
        _stats_cache.update(ts=now, stats=st)
        return st
    except Exception as e:  # noqa: BLE001
        log.warning("guardian_stats_unavailable", err=str(e))
        return _stats_cache["stats"]


def _track_record_block(st: Optional[Dict[str, Any]], risk: str) -> Dict[str, Any]:
    """Calibration for THIS risk bucket + the gate-relevant false-negative rate.
    Honest cold start: explicit insufficient_history, no invented numbers."""
    out: Dict[str, Any] = {"bucket": risk, "methodology": METHODOLOGY_URL,
                           "insufficient_history": True,
                           "observed_30d_death_rate": None,
                           "false_negative_rate": None}
    if not st or not st.get("finalized"):
        return out
    cal = st.get("calibration") or {}
    b = cal.get(risk)
    if b:
        out["observed_30d_death_rate"] = {
            "pct": b["death_rate_pct"], "dead": b["dead"], "total": b["total"]}
        out["insufficient_history"] = False
    low = cal.get("low")
    if low:
        # FN rate = death rate among tokens we rated low (would have passed).
        out["false_negative_rate"] = {
            "pct": low["death_rate_pct"], "dead": low["dead"], "total": low["total"]}
    return out


# --------------------------------------------------------------------------- #
# Advice policy (spec §3.1; env-tunable ONLY via code+METHODOLOGY version bump)
# --------------------------------------------------------------------------- #
def advice_for(risk_level: str, degraded: bool, unindexed: bool) -> str:
    if unindexed:
        return "block"           # no data is itself a signal — fail closed
    if risk_level == "high":
        return "block"
    if risk_level == "unknown":
        return "block"
    if degraded or risk_level == "medium":
        return "warn"
    return "pass"                # low — FN rate attached, never "safe"


# --------------------------------------------------------------------------- #
# The check
# --------------------------------------------------------------------------- #
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}   # canonical addr -> (ts, resp)
_CACHE_MAX = 2000


async def gate_check(address: str, caller: str) -> Dict[str, Any]:
    """Full gate decision for a token address. Never raises; never says 'safe'."""
    addr = (address or "").strip()
    if not is_valid_address(addr):
        return {"error": "invalid_address",
                "detail": "expected a TON jetton master address "
                          "(EQ…/UQ… friendly form or wc:hex raw form)"}

    now = _now()
    hitc = _cache.get(addr)
    if hitc and now - hitc[0] < CACHE_TTL:
        resp = dict(hitc[1])
        resp["cached"] = True
        await _ledger_gate(resp, caller, now)   # every check is still a receipt
        return resp

    verdict = None
    try:
        from services.verdict import check_token
        verdict = await check_token(addr)
    except Exception as e:  # noqa: BLE001
        log.warning("guardian_verdict_failed", err=str(e), addr=addr[:16])

    st = await _stats()

    if verdict is None:
        risk, degraded, unindexed = "unknown", False, True
        resp: Dict[str, Any] = {
            "address": addr, "symbol": None,
            "risk_level": risk,
            "advice": advice_for(risk, degraded, unindexed),
            "flags": ["unindexed token — no market data available; unindexed "
                      "tokens are the riskiest kind"],
            "signals": {},
            "receipt": None,
            "unindexed": True,
        }
    else:
        risk = verdict.risk_level
        degraded = bool(verdict.stale)
        resp = {
            "address": verdict.address or addr,
            "symbol": verdict.symbol,
            "risk_level": risk,
            "advice": advice_for(risk, degraded, False),
            "flags": list(verdict.flags),
            "signals": {
                "liquidity_usd": verdict.liquidity_usd,
                "volume_24h": verdict.volume_24h,
                "price_usd": verdict.price_usd,
                "top_holder_pct": verdict.top_holder_pct,
            },
            "receipt": {"verdict_id": verdict.verdict_id,
                        "ts": verdict.checked_at},
            "degraded": degraded,
        }
    resp["track_record"] = _track_record_block(st, resp["risk_level"])
    resp["disclaimer"] = ("risk signals, not guarantees; calibrated history "
                          "attached — see methodology")
    resp["cached"] = False

    if len(_cache) > _CACHE_MAX:
        _cache.clear()          # crude but bounded; entries are 60s-lived anyway
    _cache[addr] = (now, resp)
    await _ledger_gate(resp, caller, now)
    return resp


async def _ledger_gate(resp: Dict[str, Any], caller: str, now: float) -> None:
    """Append the gate_check receipt. Best-effort, never raises.

    caller identity is stored as a short hash — never raw names/keys on the
    public ledger."""
    rec = {
        "type": "gate_check",
        "address": resp.get("address"),
        "risk_level": resp.get("risk_level"),
        "advice": resp.get("advice"),
        "verdict_id": (resp.get("receipt") or {}).get("verdict_id"),
        "caller": hashlib.sha256(f"gate:{caller}".encode()).hexdigest()[:12],
        "checked_at": now,
        "cached": bool(resp.get("cached")),
    }
    rec["gate_hash"] = canonical_hash(rec)
    resp["gate_receipt"] = rec["gate_hash"]

    def _append():
        d = os.path.dirname(LEDGER_FILE)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(LEDGER_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    try:
        await asyncio.to_thread(_append)
    except Exception as e:  # noqa: BLE001
        log.warning("gate_ledger_failed", err=str(e))


__all__ = ["gate_check", "authenticate", "consume_quota", "advice_for",
           "is_valid_address", "set_clock", "FREE_CHECKS_PER_DAY"]
