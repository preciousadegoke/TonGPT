# handlers/trackrecord.py
"""
/trackrecord (+ /receipts alias) and /proof — SPEC-001 Phase 2.

The graded public track record. Three rules, inherited from the verdict engine:

1. **Misses shown before anyone asks.** Recall AND false-alarm rate AND the
   list of tokens we green-lit that died. Every rate ships its denominator.
2. **Calibrated language.** Death rates by rating bucket, no "accuracy %"
   headline theater, no claims the data can't back.
3. **Receipts are verifiable.** /proof <id> shows the canonical content hash
   for any receipt today; the same hash becomes the Merkle leaf when Phase 3
   anchors daily roots on-chain.

Render functions are pure (dict in → str out) so tests never need aiogram.
"""

from __future__ import annotations

import html
import logging
import time
from typing import Any, Dict, Optional

from aiogram import Router, types
from aiogram.filters import Command, CommandObject

logger = logging.getLogger(__name__)

router = Router()

_LVL_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢", "unknown": "⚪"}


def _esc(x) -> str:
    """HTML-escape attacker-influenced strings (token symbols, queries, ids).
    Token names/symbols come from DEX metadata — i.e. from the token deployer."""
    return html.escape(str(x if x is not None else "?"), quote=False)
_LABEL_EMOJI = {"rugged": "💀", "collapsed": "📉", "alive": "✅", "indeterminate": "❔"}
_MISSES_SHOWN = 5


# --------------------------------------------------------------------------- #
# Pure renderers
# --------------------------------------------------------------------------- #
def render_trackrecord(st: Dict[str, Any], pending: Dict[str, int],
                       issued: Dict[str, Any]) -> str:
    """The graded track-record card. Honest by construction:

    * cold start (nothing graded yet) → issued counts + maturity note
    * graded → recall, false alarms, misses, calibration — with denominators
    """
    lines = ["🧾 <b>TonGPT Track Record</b> — graded, misses included\n"]

    total_issued = issued.get("total", 0)
    if not st or not st.get("finalized"):
        if not total_issued:
            lines.append(
                "No verdicts recorded yet. Every /check and every Group Guardian "
                "scan becomes a timestamped receipt here — public from day one."
            )
        else:
            lines.append(f"Verdicts issued so far: <b>{total_issued}</b>")
            lines.append(
                f"{_LVL_EMOJI['high']} {issued.get('high', 0)}   "
                f"{_LVL_EMOJI['medium']} {issued.get('medium', 0)}   "
                f"{_LVL_EMOJI['low']} {issued.get('low', 0)}   "
                f"{_LVL_EMOJI['unknown']} {issued.get('unknown', 0)}"
            )
            lines.append(
                "\n⏳ <i>Grading in progress — every verdict is re-checked at "
                "24h, 72h, 7d and 30d and labeled rugged/collapsed/alive. "
                "The first graded results appear once verdicts mature.</i>"
            )
        lines.append(_footer())
        return "\n".join(lines)

    graded = st["finalized"]
    lines.append(
        f"📊 Graded: <b>{graded}</b> of {pending.get('total', graded)} verdicts"
        + (f" · {pending.get('maturing', 0)} still maturing" if pending.get("maturing") else "")
    )

    if st.get("recall"):
        r = st["recall"]
        lines.append(
            f"🎯 <b>Flagged {r['flagged']} of {r['dead_total']} tokens that died</b> "
            f"({r['pct']}%) — rated 🔴/🟡 before the outcome"
        )
    if st.get("false_alarm_rate"):
        fa = st["false_alarm_rate"]
        lines.append(
            f"🚨 False alarms: {fa['alive_high']} of {fa['high_total']} 🔴 calls "
            f"still alive at 30d ({fa['pct']}%)"
        )

    misses = st.get("misses") or []
    if misses:
        lines.append(f"\n📉 <b>Our misses</b> — rated 🟢/⚪, token died: {len(misses)}")
        for m in misses[:_MISSES_SHOWN]:
            lines.append(
                f"   {_LVL_EMOJI.get(m['risk_level'], '⚪')} {_esc(m.get('symbol'))} "
                f"→ {_LABEL_EMOJI.get(m['label'], '')} {_esc(m['label'])} "
                f"· receipt <code>{_esc(m['verdict_id'])}</code>"
            )
        if len(misses) > _MISSES_SHOWN:
            lines.append(f"   …and {len(misses) - _MISSES_SHOWN} more")
    else:
        lines.append("\n📉 Misses so far: <b>0</b> (rated 🟢/⚪ that died)")

    cal = st.get("calibration") or {}
    if cal:
        lines.append("\n📈 <b>30-day death rate by our rating</b>")
        for lvl in ("high", "medium", "low", "unknown"):
            b = cal.get(lvl)
            if b:
                lines.append(
                    f"   {_LVL_EMOJI[lvl]} {lvl}: {b['death_rate_pct']}% "
                    f"({b['dead']}/{b['total']})"
                )

    ex = st.get("excluded") or {}
    if ex.get("microcap") or ex.get("indeterminate"):
        lines.append(
            f"\n⏳ Excluded from rates: {ex.get('microcap', 0)} microcap (&lt;$500 liq) "
            f"· {ex.get('indeterminate', 0)} no-data — counted, never hidden"
        )

    lines.append(_footer())
    return "\n".join(lines)


def _footer() -> str:
    return (
        "\n📜 On-chain anchoring: <i>pending (SPEC-001 Phase 3 — daily Merkle "
        "root of all receipts)</i>\n"
        "Verify any receipt: <code>/proof &lt;receipt id&gt;</code>"
    )


def render_proof(hit: Optional[Dict[str, Any]], query: str,
                 anchor: Optional[Dict[str, Any]] = None) -> str:
    """Render a receipt lookup. Never overclaims: anchoring status is explicit —
    `anchor` (from services.receipts_anchor.get_anchor_info) upgrades the
    footer from "pending" to the day's root + inclusion proof when computed."""
    if hit is None:
        return (
            f"🔍 No receipt found for <code>{_esc((query or '')[:64])}</code>.\n"
            "Use the 12-char receipt id from a verdict card, or at least the "
            "first 8 characters of a receipt hash."
        )
    rec = hit["record"]
    kind = hit["kind"]
    lines = [f"🧾 <b>Receipt</b> <code>{_esc(rec.get('verdict_id'))}</code> · {kind}"]
    if kind == "verdict":
        lvl = rec.get("risk_level", "unknown")
        lines.append(
            f"{_LVL_EMOJI.get(lvl, '⚪')} <b>{_esc(rec.get('symbol'))}</b> rated "
            f"<b>{_esc(lvl)}</b> at {_fmt_ts(rec.get('checked_at'))}"
        )
        if rec.get("address"):
            lines.append(f"<code>{_esc(rec['address'])}</code>")
        h = rec.get("verdict_hash")
        if h:
            lines.append(f"\n🔐 Content hash (SHA-256, canonical JSON):\n<code>{h}</code>")
        else:
            lines.append("\n🔐 <i>Issued before content-hashing shipped — "
                         "identified by receipt id only.</i>")
        final = hit.get("final_label")
        if final:
            lines.append(f"\n⚖️ Graded outcome: {_LABEL_EMOJI.get(final, '')} <b>{final}</b>")
        else:
            lines.append("\n⚖️ Outcome: <i>still maturing (graded at 24h/72h/7d/30d)</i>")
    else:  # outcome record
        lines.append(
            f"⚖️ Final outcome for receipt <code>{_esc(rec.get('verdict_id'))}</code>: "
            f"{_LABEL_EMOJI.get(rec.get('label', ''), '')} <b>{_esc(rec.get('label'))}</b> "
            f"at {_fmt_ts(rec.get('finalized_at'))}"
        )
        if rec.get("outcome_hash"):
            lines.append(f"\n🔐 Content hash:\n<code>{rec['outcome_hash']}</code>")
    lines.append(_render_anchor_status(anchor))
    lines.append(
        "<i>To verify yourself: take the receipt's JSON from the public ledger, "
        "drop the hash fields, serialize with sorted keys and no spaces, and "
        "SHA-256 it — you get the hash above.</i>"
    )
    return "\n".join(lines)


def _render_anchor_status(anchor: Optional[Dict[str, Any]]) -> str:
    """Three honest states: no root yet / root computed / anchored on-chain."""
    if not anchor or anchor.get("status") == "pending" or not anchor.get("root"):
        return (
            "\n⛓ <b>On-chain anchor:</b> <i>pending — this hash is the exact "
            "Merkle leaf that will be anchored once its day's root is computed "
            "and sent to the registry contract, so the receipt cannot be "
            "silently rewritten later.</i>"
        )
    lines = [
        f"\n⛓ <b>Merkle anchor</b> · day {anchor.get('day')} "
        f"({anchor.get('count')} receipts)",
        f"root: <code>{anchor.get('root')}</code>",
    ]
    proof = anchor.get("proof")
    if proof is not None:
        if proof:
            shown = proof if len(proof) <= 4 else proof[:4]
            lines.append("inclusion proof (sorted-pair SHA-256):")
            for p in shown:
                lines.append(f"  <code>{p}</code>")
            if len(proof) > 4:
                lines.append(f"  …and {len(proof) - 4} more siblings")
        else:
            lines.append("<i>(only receipt of its day — the root IS this hash's parent set)</i>")
        if anchor.get("verified"):
            lines.append("✅ proof verifies against the recorded root")
    if anchor.get("tx"):
        lines.append(f"⛓ on-chain: <code>{_esc(anchor['tx'])}</code>")
    else:
        lines.append(
            "🕐 <i>root computed, awaiting the operator's on-chain anchor tx "
            "(the registry contract is append-only — once sent, immutable).</i>"
        )
    return "\n".join(lines)


def _fmt_ts(ts) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(float(ts)))
    except (TypeError, ValueError):
        return "—"


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
@router.message(Command("trackrecord", "receipts"))
async def trackrecord_command(message: types.Message):
    try:
        from services.outcome_tracker import pending_counts, track_record_stats
        from services.verdict import stats as issued_stats
        st = await track_record_stats()
        pending = await pending_counts()
        issued = await issued_stats()
    except Exception as e:  # noqa: BLE001 — degrade, never crash the chat
        logger.warning(f"trackrecord data unavailable: {type(e).__name__}: {e}")
        st, pending, issued = {}, {}, {}
    await message.reply(render_trackrecord(st, pending, issued), parse_mode="HTML")


@router.message(Command("proof"))
async def proof_command(message: types.Message, command: CommandObject = None):
    query = (command.args if command and command.args else "").strip()
    if not query:
        await message.reply(
            "🔐 <b>Verify a receipt</b>\n\n"
            "Usage: <code>/proof &lt;receipt id&gt;</code> — the 12-char id on "
            "every verdict card, or a receipt hash (first 8+ chars).\n"
            "Every TonGPT verdict is logged when it's made; /proof shows the "
            "canonical hash that pins its content.",
            parse_mode="HTML",
        )
        return
    try:
        from services.outcome_tracker import lookup_receipt
        hit = await lookup_receipt(query)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"proof lookup failed: {type(e).__name__}: {e}")
        hit = None
    anchor = None
    if hit:
        h = hit["record"].get("verdict_hash") or hit["record"].get("outcome_hash")
        if h:
            try:
                from services.receipts_anchor import get_anchor_info
                anchor = await get_anchor_info(h)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"anchor info failed: {type(e).__name__}: {e}")
    await message.reply(render_proof(hit, query, anchor), parse_mode="HTML")


__all__ = ["router", "render_trackrecord", "render_proof"]
