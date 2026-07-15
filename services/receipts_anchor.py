# services/receipts_anchor.py
"""
Receipts Anchor — SPEC-001 Phase 3. Daily Merkle roots over the receipts ledger.

Every verdict/outcome receipt already carries a canonical SHA-256 content hash
(services/outcome_tracker.canonical_hash). This module:

  1. partitions hashed ledger records into UTC days,
  2. builds a deterministic Merkle tree per day (sorted-pair SHA-256, so
     inclusion proofs need no left/right flags),
  3. appends an `anchor` record to the ledger with the day's root, and
  4. serves inclusion proofs for /proof.

SECURITY POSTURE — why this module does NOT send transactions:
The bot deliberately holds no signing key (utils/ton_wallet.send_transaction is
a stub, by design). Anchoring on-chain is an OPERATOR action: this module
computes the root and logs the exact (dayIndex, root) pair; the operator sends
it to the anchor registry contract (tongpt-subscription/contracts/
anchor_registry.tolk) from their own wallet — `node scripts/anchor_payload.js
<dayIndex> <rootHex>` prints the ready-made message body. The contract is
append-only, so even a hijacked operator key can never rewrite an anchored day.
`mark_anchored(day_index, tx)` records the tx once sent; until then /proof
reports the root as "computed, awaiting on-chain anchor" — never more.

State lives in the same SQLite index as the outcome tracker (data/receipts.db,
derived + rebuildable); the JSONL ledger remains the source of truth.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import structlog

from services.outcome_tracker import DB_FILE, LEDGER_FILE, _db  # shared index

log = structlog.get_logger(__name__)

CHECK_INTERVAL = int(os.getenv("ANCHOR_CHECK_INTERVAL", "3600"))       # loop cadence, s
BACKFILL_DAYS = int(os.getenv("ANCHOR_BACKFILL_DAYS", "30"))           # retro window
CONTRACT_ADDRESS = os.getenv("ANCHOR_CONTRACT_ADDRESS", "")            # set after deploy
ENABLED = os.getenv("ANCHOR_ENABLED", "true").lower() != "false"

_now = time.time


def set_clock(fn) -> None:
    """Test hook. None restores time.time."""
    global _now
    _now = fn or time.time


_ANCHOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS anchors (
    day_index INTEGER PRIMARY KEY,
    day       TEXT NOT NULL,
    root      TEXT NOT NULL,
    count     INTEGER NOT NULL,
    computed_at REAL NOT NULL,
    tx        TEXT,
    status    TEXT NOT NULL DEFAULT 'computed'   -- computed | anchored
);
"""


def _adb():
    conn = _db()
    conn.executescript(_ANCHOR_SCHEMA)
    return conn


# --------------------------------------------------------------------------- #
# Merkle tree — SHA-256 over sorted pairs (proofs carry no position flags)
# --------------------------------------------------------------------------- #
def _pair_hash(a: bytes, b: bytes) -> bytes:
    lo, hi = (a, b) if a <= b else (b, a)
    return hashlib.sha256(lo + hi).digest()


def merkle_root(leaves_hex: List[str]) -> Optional[str]:
    """Deterministic root over the (sorted, deduped) leaf hashes. None if empty."""
    leaves = sorted({h.lower() for h in leaves_hex})
    if not leaves:
        return None
    level = [bytes.fromhex(h) for h in leaves]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level) - 1, 2):
            nxt.append(_pair_hash(level[i], level[i + 1]))
        if len(level) % 2 == 1:
            nxt.append(level[-1])          # odd node promoted unchanged
        level = nxt
    return level[0].hex()


def merkle_proof(leaves_hex: List[str], leaf_hex: str) -> Optional[List[str]]:
    """Sibling path for ``leaf_hex``. None if the leaf is not in the set."""
    leaves = sorted({h.lower() for h in leaves_hex})
    target = leaf_hex.lower()
    if target not in leaves:
        return None
    level = [bytes.fromhex(h) for h in leaves]
    idx = leaves.index(target)
    proof: List[str] = []
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level) - 1, 2):
            nxt.append(_pair_hash(level[i], level[i + 1]))
        odd = len(level) % 2 == 1
        if odd:
            nxt.append(level[-1])
        if odd and idx == len(level) - 1:
            idx = len(nxt) - 1             # promoted unchanged, no sibling
        else:
            sib = idx + 1 if idx % 2 == 0 else idx - 1
            proof.append(level[sib].hex())
            idx = idx // 2
        level = nxt
    return proof


def verify_proof(leaf_hex: str, proof: List[str], root_hex: str) -> bool:
    h = bytes.fromhex(leaf_hex.lower())
    for sib in proof:
        h = _pair_hash(h, bytes.fromhex(sib.lower()))
    return h.hex() == root_hex.lower()


# --------------------------------------------------------------------------- #
# Ledger partitioning
# --------------------------------------------------------------------------- #
def _record_leaf_and_ts(rec: Dict[str, Any]) -> Optional[Tuple[str, float]]:
    """(hash, timestamp) for a ledger record, or None if unhashed/not a receipt."""
    t = rec.get("type")
    if t == "anchor":
        return None
    if t == "outcome":
        h, ts = rec.get("outcome_hash"), rec.get("finalized_at")
    else:
        h, ts = rec.get("verdict_hash"), rec.get("checked_at")
    if not h or not ts:
        return None
    return str(h), float(ts)


def day_index_of(ts: float) -> int:
    return int(ts // 86400)


def day_str(day_index: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(day_index * 86400))


def _leaves_by_day() -> Dict[int, List[str]]:
    """Scan the ledger and bucket receipt hashes into UTC day indexes."""
    out: Dict[int, List[str]] = {}
    if not os.path.exists(LEDGER_FILE):
        return out
    with open(LEDGER_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            lt = _record_leaf_and_ts(rec)
            if lt is None:
                continue
            out.setdefault(day_index_of(lt[1]), []).append(lt[0])
    return out


# --------------------------------------------------------------------------- #
# Anchoring passes
# --------------------------------------------------------------------------- #
def _ledger_anchor_record(day_index: int, root: str, count: int, now: float) -> None:
    rec = {"type": "anchor", "day": day_str(day_index), "day_index": day_index,
           "merkle_root": root, "count": count, "computed_at": now,
           "tx": None, "contract": CONTRACT_ADDRESS or None}
    with open(LEDGER_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


async def anchor_once() -> Dict[str, int]:
    """Compute roots for every COMPLETE past UTC day (within the backfill
    window) that has receipts but no anchor row yet. Idempotent. Returns
    counters for tests/observability."""
    now = _now()
    today = day_index_of(now)
    stats = {"computed": 0, "skipped_existing": 0}

    def _work():
        conn = _adb()
        try:
            have = {d for (d,) in conn.execute("SELECT day_index FROM anchors").fetchall()}
            by_day = _leaves_by_day()
            for day, leaves in sorted(by_day.items()):
                if day >= today:            # only completed days are anchorable
                    continue
                if day < today - BACKFILL_DAYS:
                    continue
                if day in have:
                    stats["skipped_existing"] += 1
                    continue
                root = merkle_root(leaves)
                if root is None:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO anchors "
                    "(day_index, day, root, count, computed_at) VALUES (?,?,?,?,?)",
                    (day, day_str(day), root, len(set(leaves)), now),
                )
                _ledger_anchor_record(day, root, len(set(leaves)), now)
                stats["computed"] += 1
                log.warning(
                    "anchor_root_computed",
                    day=day_str(day), day_index=day, root=root, count=len(set(leaves)),
                    action=("send with: node scripts/anchor_payload.js "
                            f"{day} {root}"),
                )
            conn.commit()
        finally:
            conn.close()
    await asyncio.to_thread(_work)
    return stats


async def mark_anchored(day_index: int, tx: str) -> bool:
    """Record the on-chain tx for a computed day (operator confirmation)."""
    def _mark():
        conn = _adb()
        try:
            cur = conn.execute(
                "UPDATE anchors SET tx=?, status='anchored' WHERE day_index=? AND tx IS NULL",
                (tx, day_index),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
    return await asyncio.to_thread(_mark)


# --------------------------------------------------------------------------- #
# Proof serving (consumed by /proof)
# --------------------------------------------------------------------------- #
async def get_anchor_info(leaf_hash: str) -> Optional[Dict[str, Any]]:
    """Anchor status + inclusion proof for a receipt hash, or None if its day
    has no computed root yet."""
    leaf = (leaf_hash or "").lower()

    def _work():
        by_day = _leaves_by_day()
        for day, leaves in by_day.items():
            if leaf in {h.lower() for h in leaves}:
                conn = _adb()
                try:
                    row = conn.execute(
                        "SELECT root, count, tx, status, day FROM anchors WHERE day_index=?",
                        (day,),
                    ).fetchone()
                finally:
                    conn.close()
                if not row:
                    return {"day_index": day, "day": day_str(day), "status": "pending"}
                root, count, tx, status, dstr = row
                proof = merkle_proof(leaves, leaf)
                return {
                    "day_index": day, "day": dstr, "root": root, "count": count,
                    "tx": tx, "status": status, "proof": proof,
                    "contract": CONTRACT_ADDRESS or None,
                    "verified": bool(proof is not None and verify_proof(leaf, proof, root)),
                }
        return None
    return await asyncio.to_thread(_work)


# --------------------------------------------------------------------------- #
# Supervised loop (main.py, MAIN-001 pattern)
# --------------------------------------------------------------------------- #
async def anchor_loop(interval: Optional[int] = None) -> None:
    if not ENABLED:
        log.info("receipts_anchor_disabled", reason="ANCHOR_ENABLED=false")
        return
    interval = interval or CHECK_INTERVAL
    log.info("receipts_anchor_started", interval=interval,
             contract=CONTRACT_ADDRESS or "(not deployed yet)")
    while True:
        try:
            s = await anchor_once()
            if s["computed"]:
                log.info("anchor_pass", **s)
        except Exception as e:  # noqa: BLE001 — never kill the loop
            log.error("anchor_pass_error", err=str(e))
        await asyncio.sleep(interval)


__all__ = [
    "merkle_root", "merkle_proof", "verify_proof",
    "anchor_once", "anchor_loop", "mark_anchored", "get_anchor_info",
    "day_index_of", "day_str", "set_clock",
]
