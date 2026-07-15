# TonGPT Guardian Gate — MCP Server

The pre-trade safety oracle for TON, as an MCP tool. One config entry gives
your agent a hard gate against rugs — with a **graded, on-chain-anchored track
record** attached to every answer, not just a score.

```
Agent about to buy jetton EQ…  →  ton_token_safety_check(address)
  ← advice: "block"  ·  flags: ["dev wallet 41%", "LP unlocked"]
  ← track_record: high-risk calls were dead within 30d 82% of the time (23/28)
  ← gate receipt hash — every answer is ledgered, graded later, Merkle-anchored
```

## Why this exists

TON Agentic Wallets (April 2026) give AI agents budgeted wallets, but the
standard governs *how much* an agent can spend — not *what is safe to buy*.
Guardian Gate is the missing layer. Semantics are calibrated and honest:

| advice | meaning |
|---|---|
| `block` | high risk, **or unindexed/unknown** — no data is itself a risk signal; fail closed |
| `warn` | medium risk, or market data degraded |
| `pass` | no major risk signals detected — **never "safe"**; the observed false-negative rate ships in the response |

Methodology (labels, thresholds, honesty rules): `docs/METHODOLOGY.md` in the
TonGPT repo. Any receipt can be audited via the bot's `/proof <hash>`.

## Setup

Requirements: Node ≥ 18 (global `fetch`). **Zero dependencies** — the server
is a single auditable file speaking JSON-RPC over stdio.

1. Get an API key from the TonGPT operator.
2. Add the server to your agent's MCP config:

```json
{
  "mcpServers": {
    "tongpt-guardian": {
      "command": "node",
      "args": ["/path/to/scripts/guardian-mcp/server.js"],
      "env": {
        "GUARDIAN_API_URL": "https://YOUR-TONGPT-HOST",
        "GUARDIAN_API_KEY": "your-key-here"
      }
    }
  }
}
```

That block works as-is for Claude Desktop (`claude_desktop_config.json`),
Claude Code (`.mcp.json`), and any framework using the standard MCP config
shape. For TON Agentic Wallets CLI setups, register the same command as a
tool server and instruct the agent: **"call ton_token_safety_check before any
jetton purchase; never buy on `block`."**

## Tools

### `ton_token_safety_check(address)`
`address` = jetton master, friendly (`EQ…`/`UQ…`) or raw (`0:<hex>`) form.
Returns risk level, advice, named flags, market signals, the verifiable
receipt hash, and the calibration for this risk bucket (with denominators).

### `ton_track_record()`
TonGPT's full graded record: recall on tokens that died, false-alarm rate,
the misses list, per-bucket 30-day death rates, exclusions. Use it to decide
how much weight your agent gives the gate.

## Verify it works

```bash
node server.js --selftest          # protocol + fail-closed behavior, mocked HTTP
curl -H "X-API-Key: $KEY" "$URL/api/guardian/check/EQ<some-address>"
```

## Failure semantics (important for agent authors)

Network errors, timeouts, 5xx, quota exhaustion — every failure mode returns
an `isError` result telling the agent to **treat the token as blocked**. The
gate never fails open, and your agent shouldn't either.

## Rate limits

Free tier: `GUARDIAN_FREE_PER_DAY` checks/day per key (default 200). Responses
are cached ~60s per token server-side; every check (cached included) is still
receipted and graded — the gate's own accuracy is public at `/trackrecord`.
