# services/outcome_tracker.py
"""
Outcome Tracker — SPEC-001 Phase 1. Grades every verdict the bot ever issued.

The verdict engine (services/verdict.py) writes an append-only receipts ledger
(data/verdicts.jsonl). This module revisits each ledgered verdict on a fixed
schedule (T+24h, T+72h, T+7d, T+30d), labels the token's fate, and appends
outcome records — so the public track record ("flagged N of the last M rugs
early, missed K") is computed from data, not vibes.

Design rules (mirroring the codebase's house style):
  * JSONL ledger stays the source of truth; SQLite (data/receipts.db) is a
    derived, rebuildable index. The original verdict record is NEVER mutated.
  * Never raises out of the loop; degraded data → honest `indeterminate`
    labels, never guesses.
  * Labeling criteria follow the rug-pull literature (see SPEC-001 §3.2):
    near-total liquidity withdrawal + activity cessation + price collapse,
    sustained across ≥72h, with an explicit recovery guard so a dip is not a rug.
  * Testable by construction: market data fetch and clock are injectable.

Labels
------
  rugged        liquidity −≥95% from verdict time AND (volume ≈ 0 OR price −≥90%),
                confirmed by two consecutive snapshots ≥72h apart
  collapsed     price −≥90% AND volume ≈ 0, liquidity not clearly pulled
                (slow rug / abandonment), confirmed the same way
  alive         still has ≥$1k liquidity and nonzero volume at T+30d
  microcap      liquidity at verdict time < $500 — tracked but EXCLUDED from
                headline stats (no padding wins with dust tokens)
  indeterminate market data unavailable — excluded from accuracy stats but
                counted and disclosed
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import structlog

log = structlog.get_logger(__name__)

# --------------------------------------------------------------------------- #
# Config (env-overridable, spec defaults)
# --------------------------------------------------------------------------- #
LEDGER_FILE = os.getenv("VERDICT_LEDGER_FILE", os.path.join("data", "verdicts.jsonl"))
DB_FILE = os.getenv("OUTCOME_DB_FILE", os.path.join("data", "receipts.db"))
EVAL_INTERVAL = int(os.getenv("OUTCOME_EVAL_INTERVAL", "3600"))          # loop cadence, s
# Backpressure: max distinct tokens fetched per pass. A huge backlog (first run
# on an old ledger) drains across several passes instead of hammering the API.
MAX_FETCH_PER_PASS = int(os.getenv("OUTCOME_MAX_FETCH_PER_PASS", "200"))

# Evaluation horizons after the verdict, in seconds (spec §3.2).
HORIZONS: List[Tuple[str, int]] = [
    ("24h", 24 * 3600),
    ("72h", 72 * 3600),
    ("7d", 7 * 86400),
    ("30d", 30 * 86400),
]

LIQ_RUG_DROP_PCT = float(os.getenv("OUTCOME_LIQ_RUG_DROP_PCT", "95"))    # liq −≥95% → pulled
PX_DEAD_DRAWDOWN_PCT = float(os.getenv("OUTCOME_PX_DEAD_DRAWDOWN_PCT", "90"))
VOL_DEAD_USD = float(os.getenv("OUTCOME_VOL_DEAD_USD", "10"))            # 24h vol ≈ 0
ALIVE_MIN_LIQ_USD = float(os.getenv("OUTCOME_ALIVE_MIN_LIQ_USD", "1000"))
MICROCAP_MIN_LIQ_USD = float(os.getenv("OUTCOME_MICROCAP_MIN_LIQ_USD", "500"))

# Injectable for tests: async fn(address_or_symbol) -> dict | None with keys
# liquidity_usd, price_usd, volume_24h, ok (bool). None = fetch failed.
MarketFetcher = Callable[[str], Awaitable[Optional[Dict[str, Any]]]]
_market_fetcher: Optional[MarketFetcher] = None
_now: Callable[[], float] = time.time


def set_market_fetcher(fn: Optional[MarketFetcher]) -> None:
    """Test/DI hook. None restores the default (dexscreener)."""
    global _market_fetcher
    _market_fetcher = fn


def set_clock(fn: Optional[Callable[[], float]]) -> None:
    """Test hook for time travel. None restores time.time."""
    global _now
    _now = fn or time.time


async def _default_fetch(query: str) -> Optional[Dict[str, Any]]:
    try:
        from services.dexscreener_service import get_token_info
        m = await get_token_info(query)
    except Exception as e:  # noqa: BLE001
        log.debug("outcome_fetch_failed", query=query[:32], err=str(e))
        return None
    if not m or not getattr(m, "ok", False) or getattr(m, "stale", False):
        return None
    return {
        "ok": True,
        "liquidity_usd": m.liquidity_usd,
        "price_usd": m.price_usd,
        "volume_24h": m.volume_24h,
    }


# --------------------------------------------------------------------------- #
# Canonical hashing (spec §3.1) — stable across dict ordering
# --------------------------------------------------------------------------- #
def canonical_hash(record: Dict[str, Any]) -> str:
    """SHA-256 over canonical JSON (sorted keys, no whitespace variance).

    Any pre-existing hash field is excluded so the hash is reproducible from
    the record content itself.
    """
    clean = {k: v for k, v in record.items() if k not in ("verdict_hash", "outcome_hash")}
    blob = json.dumps(clean, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# SQLite index (derived; rebuildable from the JSONL ledger)
# --------------------------------------------------------------------------- #
_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS verdicts (
    verdict_id   TEXT PRIMARY KEY,
    verdict_hash TEXT,
    address      TEXT,
    symbol       TEXT,
    risk_level   TEXT,
    checked_at   REAL,
    liq0         REAL,
    px0          REAL,
    microcap     INTEGER DEFAULT 0,
    final_label  TEXT,
    finalized_at REAL
);
CREATE TABLE IF NOT EXISTS outcomes (
    verdict_id  TEXT NOT NULL,
    horizon     TEXT NOT NULL,
    checked_at  REAL NOT NULL,
    label       TEXT NOT NULL,
    signals     TEXT,
    PRIMARY KEY (verdict_id, horizon)
);
CREATE INDEX IF NOT EXISTS idx_verdicts_final ON verdicts (final_label);
"""


def _db() -> sqlite3.Connection:
    d = os.path.dirname(DB_FILE)
    if d:
        os.makedirs(d, exist_ok=True)
    # check_same_thread=False: the connection hops between asyncio.to_thread
    # workers; all access is sequential (one pass at a time), never concurrent.
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.executescript(_SCHEMA)
    return conn


# --------------------------------------------------------------------------- #
# Ledger ingestion — pick up verdicts the index hasn't seen yet
# --------------------------------------------------------------------------- #
def _ingest_ledger(conn: sqlite3.Connection) -> int:
    """Read new JSONL lines past the stored byte offset into the index.

    Byte-offset (not line-count) tracking so a partially-written last line is
    retried next pass rather than skipped forever.
    """
    if not os.path.exists(LEDGER_FILE):
        return 0
    row = conn.execute("SELECT value FROM meta WHERE key='ledger_offset'").fetchone()
    offset = int(row[0]) if row else 0
    size = os.path.getsize(LEDGER_FILE)
    if size < offset:                      # ledger rotated/replaced: reindex
        log.warning("outcome_ledger_shrunk_reindexing", old=offset, new=size)
        offset = 0
    ingested = 0
    with open(LEDGER_FILE, "r", encoding="utf-8") as f:
        f.seek(offset)
        while True:
            pos = f.tell()
            line = f.readline()
            if not line:
                break
            if not line.endswith("\n"):    # torn tail — retry next pass
                offset = pos
                break
            offset = f.tell()
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                log.warning("outcome_ledger_bad_line", head=line[:80])
                continue
            if rec.get("type") in ("outcome", "anchor"):
                continue                    # our own appended records
            vid = rec.get("verdict_id")
            if not vid:
                continue
            liq0 = rec.get("liquidity_usd")
            conn.execute(
                "INSERT OR IGNORE INTO verdicts "
                "(verdict_id, verdict_hash, address, symbol, risk_level, checked_at, "
                " liq0, px0, microcap) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    vid,
                    rec.get("verdict_hash") or canonical_hash(rec),
                    rec.get("address"),
                    rec.get("symbol"),
                    rec.get("risk_level", "unknown"),
                    float(rec.get("checked_at") or 0),
                    liq0,
                    rec.get("price_usd"),
                    1 if (liq0 is not None and liq0 < MICROCAP_MIN_LIQ_USD) else 0,
                ),
            )
            ingested += 1
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('ledger_offset', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(offset),),
    )
    conn.commit()
    return ingested


# --------------------------------------------------------------------------- #
# Snapshot classification (one horizon, one token)
# --------------------------------------------------------------------------- #
def _classify_snapshot(
    liq0: Optional[float], px0: Optional[float], market: Optional[Dict[str, Any]]
) -> Tuple[str, Dict[str, Any]]:
    """Return (snapshot_label, signals). Labels: rugged|collapsed|alive|indeterminate."""
    if not market or not market.get("ok"):
        return "indeterminate", {"reason": "no_market_data"}

    liq = market.get("liquidity_usd")
    px = market.get("price_usd")
    vol = market.get("volume_24h")

    signals: Dict[str, Any] = {"liq_usd": liq, "px_usd": px, "vol_24h": vol}

    liq_drop = None
    if liq0 and liq0 > 0 and liq is not None:
        liq_drop = max(0.0, (1 - liq / liq0) * 100)
        signals["liq_drop_pct"] = round(liq_drop, 2)
    px_dd = None
    if px0 and px0 > 0 and px is not None:
        px_dd = max(0.0, (1 - px / px0) * 100)
        signals["px_drawdown_pct"] = round(px_dd, 2)

    dead_liq = liq_drop is not None and liq_drop >= LIQ_RUG_DROP_PCT
    dead_px = px_dd is not None and px_dd >= PX_DEAD_DRAWDOWN_PCT
    dead_vol = vol is not None and vol < VOL_DEAD_USD

    if dead_liq and (dead_vol or dead_px):
        return "rugged", signals
    if dead_px and dead_vol:
        return "collapsed", signals
    # Recovery guard is implicit: a healthy snapshot after a dead one simply
    # classifies as alive here, and finalization requires TWO consecutive dead
    # snapshots ≥72h apart — so a dip-then-recovery can never finalize as a rug.
    return "alive", signals


# --------------------------------------------------------------------------- #
# Finalization — sustained-≥72h rule (spec §3.2)
# --------------------------------------------------------------------------- #
_DEAD = ("rugged", "collapsed")
# Snapshot labels that carry no evidence either way.
_NO_EVIDENCE = ("indeterminate", "skipped")
# Horizon pairs that are ≥72h apart and adjacent in the schedule.
_CONFIRM_PAIRS = [("72h", "7d"), ("7d", "30d")]


def _finalize(conn: sqlite3.Connection, vid: str) -> Optional[str]:
    """Compute the final label if it can be decided now, else None.

    Rules:
      * two consecutive dead snapshots ≥72h apart → final dead label (early exit)
      * at 30d the 30d snapshot decides. A dead 30d snapshot with a LIVE 7d
        snapshot cannot prove ≥72h sustainment → `indeterminate`. A dead 30d
        snapshot whose 7d snapshot carries no evidence (skipped during downtime,
        or data-gap) keeps the dead label — a drained pool does not refill, and
        the 30d horizon is the horizon of record (SPEC-001 §3.2).
      * `skipped` snapshots (catch-up after downtime) never count as evidence.
    """
    rows = dict(
        (h, l) for h, l in conn.execute(
            "SELECT horizon, label FROM outcomes WHERE verdict_id=?", (vid,)
        ).fetchall()
    )
    # Early confirmation: consecutive dead pair.
    for a, b in _CONFIRM_PAIRS:
        la, lb = rows.get(a), rows.get(b)
        if la in _DEAD and lb in _DEAD:
            return lb if la == lb else "rugged"  # liq-pull evidence dominates
    if "30d" in rows:
        final = rows["30d"]
        if final == "skipped":
            return "indeterminate"
        if final in _DEAD and rows.get("7d") not in _DEAD:
            final = final if rows.get("7d") in _NO_EVIDENCE else "indeterminate"
        return final
    return None


# --------------------------------------------------------------------------- #
# One evaluation pass
# --------------------------------------------------------------------------- #
async def evaluate_once() -> Dict[str, int]:
    """Ingest new ledger lines and run every due evaluation. Idempotent.

    Returns counters for observability/tests.
    """
    fetch = _market_fetcher or _default_fetch
    now = _now()
    stats = {"ingested": 0, "evaluated": 0, "finalized": 0, "fetch_failures": 0}

    def _open() -> sqlite3.Connection:
        return _db()

    conn = await asyncio.to_thread(_open)
    try:
        stats["ingested"] = await asyncio.to_thread(_ingest_ledger, conn)

        due: List[Tuple[str, str, Optional[str], Optional[float], Optional[float], str, int]] = []

        ages: Dict[str, float] = {}

        def _collect():
            for vid, addr, symbol, liq0, px0, risk, micro, checked_at in conn.execute(
                "SELECT verdict_id, address, symbol, liq0, px0, risk_level, microcap, checked_at "
                "FROM verdicts WHERE final_label IS NULL"
            ).fetchall():
                ages[vid] = round((now - checked_at) / 86400, 2)
                done = {h for (h,) in conn.execute(
                    "SELECT horizon FROM outcomes WHERE verdict_id=?", (vid,)
                ).fetchall()}
                pending = [h for h, s in HORIZONS if h not in done and checked_at + s <= now]
                if not pending:
                    continue
                # Integrity of the sustainment rule: only the LATEST due horizon
                # gets a real market snapshot this pass. Earlier ones (overdue
                # because the tracker was down) are marked `skipped` — grading
                # four horizons from one instant would fake a ≥72h confirmation.
                for hname in pending[:-1]:
                    conn.execute(
                        "INSERT OR IGNORE INTO outcomes "
                        "(verdict_id, horizon, checked_at, label, signals) VALUES (?,?,?,?,?)",
                        (vid, hname, now, "skipped",
                         json.dumps({"reason": "catch_up_after_downtime"})),
                    )
                due.append((vid, pending[-1], addr or symbol, liq0, px0, risk, micro))
            conn.commit()
        await asyncio.to_thread(_collect)

        # One market fetch per token per pass (dedupe), capped for backpressure.
        markets: Dict[str, Optional[Dict[str, Any]]] = {}
        deferred: set = set()
        for _vid, _h, query, *_rest in due:
            if query in markets or query in deferred:
                continue
            if len(markets) >= MAX_FETCH_PER_PASS:
                deferred.add(query)          # evaluated on a later pass
                continue
            markets[query] = await fetch(query) if query else None
            if markets[query] is None:
                stats["fetch_failures"] += 1
        if deferred:
            due = [d for d in due if d[2] not in deferred]
            log.info("outcome_backpressure", deferred_tokens=len(deferred))

        def _apply():
            finalized: set = set()
            for vid, hname, query, liq0, px0, _risk, _micro in due:
                if vid in finalized:
                    continue
                label, signals = _classify_snapshot(liq0, px0, markets.get(query))
                signals["age_days"] = ages.get(vid)
                conn.execute(
                    "INSERT OR IGNORE INTO outcomes "
                    "(verdict_id, horizon, checked_at, label, signals) VALUES (?,?,?,?,?)",
                    (vid, hname, now, label, json.dumps(signals, ensure_ascii=False)),
                )
                stats["evaluated"] += 1
                final = _finalize(conn, vid)
                if final is not None:
                    conn.execute(
                        "UPDATE verdicts SET final_label=?, finalized_at=? WHERE verdict_id=?",
                        (final, now, vid),
                    )
                    finalized.add(vid)
                    stats["finalized"] += 1
                    _ledger_outcome(vid, final, now)
            conn.commit()
        await asyncio.to_thread(_apply)
    finally:
        conn.close()

    if stats["evaluated"] or stats["ingested"]:
        log.info("outcome_pass", **stats)
    return stats


def _ledger_outcome(vid: str, final: str, now: float) -> None:
    """Append the final outcome to the JSONL ledger (the anchored artifact)."""
    rec = {"type": "outcome", "verdict_id": vid, "label": final, "finalized_at": now}
    rec["outcome_hash"] = canonical_hash(rec)
    try:
        d = os.path.dirname(LEDGER_FILE)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(LEDGER_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        log.warning("outcome_ledger_append_failed", err=str(e))


# --------------------------------------------------------------------------- #
# Track-record aggregation (consumed by /trackrecord in Phase 2)
# --------------------------------------------------------------------------- #
async def track_record_stats() -> Dict[str, Any]:
    """Aggregate the graded ledger. All rates ship with their denominators."""
    def _q() -> Dict[str, Any]:
        conn = _db()
        try:
            out: Dict[str, Any] = {"finalized": 0, "labels": {}, "calibration": {},
                                   "recall": None, "false_alarm_rate": None,
                                   "misses": [], "excluded": {"microcap": 0, "indeterminate": 0}}
            rows = conn.execute(
                "SELECT risk_level, final_label, microcap, verdict_id, symbol "
                "FROM verdicts WHERE final_label IS NOT NULL"
            ).fetchall()
            dead_total = flagged_dead = 0
            high_total = high_alive = 0
            buckets: Dict[str, Dict[str, int]] = {}
            for risk, label, micro, vid, symbol in rows:
                out["finalized"] += 1
                out["labels"][label] = out["labels"].get(label, 0) + 1
                if micro:
                    out["excluded"]["microcap"] += 1
                    continue
                if label == "indeterminate":
                    out["excluded"]["indeterminate"] += 1
                    continue
                b = buckets.setdefault(risk, {"dead": 0, "total": 0})
                b["total"] += 1
                if label in _DEAD:
                    b["dead"] += 1
                    dead_total += 1
                    if risk in ("high", "medium"):
                        flagged_dead += 1
                    else:
                        out["misses"].append({"verdict_id": vid, "symbol": symbol,
                                              "risk_level": risk, "label": label})
                if risk == "high":
                    high_total += 1
                    if label == "alive":
                        high_alive += 1
            if dead_total:
                out["recall"] = {"flagged": flagged_dead, "dead_total": dead_total,
                                 "pct": round(100 * flagged_dead / dead_total, 1)}
            if high_total:
                out["false_alarm_rate"] = {"alive_high": high_alive, "high_total": high_total,
                                           "pct": round(100 * high_alive / high_total, 1)}
            out["calibration"] = {
                r: {"dead": b["dead"], "total": b["total"],
                    "death_rate_pct": round(100 * b["dead"] / b["total"], 1)}
                for r, b in buckets.items() if b["total"]
            }
            return out
        finally:
            conn.close()
    return await asyncio.to_thread(_q)


# --------------------------------------------------------------------------- #
# Phase-2 helpers: receipt lookup + maturity counts (consumed by /trackrecord)
# --------------------------------------------------------------------------- #
async def pending_counts() -> Dict[str, int]:
    """How many verdicts exist vs. how many have a final grade."""
    def _q():
        conn = _db()
        try:
            total = conn.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0]
            done = conn.execute(
                "SELECT COUNT(*) FROM verdicts WHERE final_label IS NOT NULL"
            ).fetchone()[0]
            return {"total": total, "finalized": done, "maturing": total - done}
        finally:
            conn.close()
    return await asyncio.to_thread(_q)


async def lookup_receipt(query: str) -> Optional[Dict[str, Any]]:
    """Find a ledgered receipt by verdict_id, or by verdict/outcome hash prefix.

    Returns {"kind": "verdict"|"outcome", "record": <ledger dict>,
             "final_label": <str|None>} or None. Prefix lookups need >=8 chars
    to avoid ambiguous matches; on ambiguity the first ledger hit wins (the
    ledger is append-only, so this is stable).
    """
    q = (query or "").strip().lower()
    if not q or len(q) < 8 or not all(c in "0123456789abcdef" for c in q):
        return None

    def _scan() -> Optional[Dict[str, Any]]:
        if not os.path.exists(LEDGER_FILE):
            return None
        hit = None
        with open(LEDGER_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = "outcome" if rec.get("type") == "outcome" else (
                    "anchor" if rec.get("type") == "anchor" else "verdict")
                if kind == "anchor":
                    continue
                vid = str(rec.get("verdict_id", "")).lower()
                h = str(rec.get("verdict_hash") or rec.get("outcome_hash") or "").lower()
                if vid.startswith(q) or (h and h.startswith(q)):
                    hit = {"kind": kind, "record": rec}
                    break
        if hit is None:
            return None
        conn = _db()
        try:
            row = conn.execute(
                "SELECT final_label FROM verdicts WHERE verdict_id=?",
                (hit["record"].get("verdict_id"),),
            ).fetchone()
            hit["final_label"] = row[0] if row else None
        finally:
            conn.close()
        return hit
    return await asyncio.to_thread(_scan)


# --------------------------------------------------------------------------- #
# Supervised loop (wired in main.py under _spawn_supervised, MAIN-001 pattern)
# --------------------------------------------------------------------------- #
async def outcome_loop(interval: Optional[int] = None) -> None:
    interval = interval or EVAL_INTERVAL
    log.info("outcome_tracker_started", interval=interval, ledger=LEDGER_FILE, db=DB_FILE)
    while True:
        try:
            await evaluate_once()
        except Exception as e:  # noqa: BLE001 — never kill the loop
            log.error("outcome_pass_error", err=str(e))
        await asyncio.sleep(interval)


__all__ = [
    "evaluate_once", "outcome_loop", "track_record_stats",
    "pending_counts", "lookup_receipt",
    "canonical_hash", "set_market_fetcher", "set_clock",
    "HORIZONS", "LEDGER_FILE", "DB_FILE",
]
