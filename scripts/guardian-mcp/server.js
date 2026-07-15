#!/usr/bin/env node
/**
 * TonGPT Guardian Gate — MCP server (SPEC-002 Phase 2).
 *
 * Exposes the pre-trade safety oracle to any MCP-capable agent framework
 * (Claude, GPT agents, TON Agentic Wallets tooling) as two tools:
 *
 *   ton_token_safety_check(address)  — calibrated block|warn|pass advice with
 *                                      flags, signals, receipt hash and the
 *                                      graded track record inline
 *   ton_track_record()               — TonGPT's public graded record: recall,
 *                                      false alarms, misses, calibration
 *
 * ZERO runtime dependencies by design: the stdio MCP transport is plain
 * JSON-RPC 2.0 over stdin/stdout, and Node >= 18 ships global fetch. Nothing
 * to install, nothing to audit beyond this file.
 *
 * Config (env):
 *   GUARDIAN_API_URL   base URL of the TonGPT API (e.g. https://api.tongpt.xyz)
 *   GUARDIAN_API_KEY   your key (issued by the TonGPT operator)
 *
 * Run:        node server.js
 * Self-test:  node server.js --selftest   (mocked HTTP, exercises the protocol)
 */

'use strict';

const API_URL = (process.env.GUARDIAN_API_URL || 'http://localhost:8080').replace(/\/+$/, '');
const API_KEY = process.env.GUARDIAN_API_KEY || '';

const PROTOCOL_VERSION = '2024-11-05';
const SERVER_INFO = { name: 'tongpt-guardian-gate', version: '1.0.0' };

const TOOLS = [
    {
        name: 'ton_token_safety_check',
        description:
            'Pre-trade safety check for a TON jetton. Returns calibrated advice ' +
            '(block | warn | pass) with named risk flags, market signals, a ' +
            'verifiable receipt hash, and TonGPT’s graded track record for ' +
            'this risk bucket. IMPORTANT semantics: "pass" NEVER means safe — ' +
            'it means no major risk signals were detected, and the response ' +
            'includes the historically observed false-negative rate. "block" on ' +
            'unindexed tokens is deliberate: no data is itself a risk signal. ' +
            'Agents should treat advice as a hard gate: do not buy on "block".',
        inputSchema: {
            type: 'object',
            properties: {
                address: {
                    type: 'string',
                    description: 'TON jetton master address (EQ…/UQ… friendly form or wc:hex raw form)',
                },
            },
            required: ['address'],
        },
    },
    {
        name: 'ton_track_record',
        description:
            'TonGPT’s public graded track record: how many verdicts were graded, ' +
            'recall on tokens that died, false-alarm rate, the misses list, and the ' +
            '30-day death rate per risk bucket — every rate with its denominator. ' +
            'Use this to calibrate how much weight to give ton_token_safety_check.',
        inputSchema: { type: 'object', properties: {} },
    },
];

// --------------------------------------------------------------------------- #
// HTTP client (injectable for --selftest)
// --------------------------------------------------------------------------- #
let httpGet = async function (path) {
    const res = await fetch(API_URL + path, {
        headers: { 'X-API-Key': API_KEY, 'Accept': 'application/json' },
        signal: AbortSignal.timeout(15000),
    });
    const body = await res.text();
    let json;
    try { json = JSON.parse(body); } catch { json = { raw: body.slice(0, 500) }; }
    return { status: res.status, json };
};

// --------------------------------------------------------------------------- #
// Tool implementations
// --------------------------------------------------------------------------- #
async function callTool(name, args) {
    if (name === 'ton_token_safety_check') {
        const address = String((args && args.address) || '').trim();
        if (!address) {
            return err('address is required');
        }
        const { status, json } = await httpGet(
            '/api/guardian/check/' + encodeURIComponent(address));
        if (status === 401) return err('invalid or missing GUARDIAN_API_KEY');
        if (status === 429) return err('daily check quota exceeded — try again tomorrow or upgrade');
        if (status === 400) return err('invalid TON address: ' + (json.detail || address));
        if (status !== 200) return err('gate unavailable (HTTP ' + status + ') — FAIL CLOSED: treat as block');
        return ok(json);
    }
    if (name === 'ton_track_record') {
        const { status, json } = await httpGet('/api/guardian/trackrecord');
        if (status === 401) return err('invalid or missing GUARDIAN_API_KEY');
        if (status !== 200) return err('track record unavailable (HTTP ' + status + ')');
        return ok(json);
    }
    return err('unknown tool: ' + name);
}

function ok(obj) {
    return { content: [{ type: 'text', text: JSON.stringify(obj, null, 2) }] };
}
function err(message) {
    return { content: [{ type: 'text', text: message }], isError: true };
}

// --------------------------------------------------------------------------- #
// JSON-RPC 2.0 over stdio (newline-delimited)
// --------------------------------------------------------------------------- #
async function handleMessage(msg) {
    const { id, method, params } = msg;
    const respond = (result) => ({ jsonrpc: '2.0', id, result });
    const fail = (code, message) => ({ jsonrpc: '2.0', id, error: { code, message } });

    switch (method) {
        case 'initialize':
            return respond({
                protocolVersion: (params && params.protocolVersion) || PROTOCOL_VERSION,
                capabilities: { tools: {} },
                serverInfo: SERVER_INFO,
            });
        case 'notifications/initialized':
        case 'notifications/cancelled':
            return null;                                   // notifications: no reply
        case 'ping':
            return respond({});
        case 'tools/list':
            return respond({ tools: TOOLS });
        case 'tools/call': {
            if (!params || typeof params.name !== 'string') {
                return fail(-32602, 'params.name required');
            }
            try {
                return respond(await callTool(params.name, params.arguments || {}));
            } catch (e) {
                // Network/parse failures NEVER become a silent pass.
                return respond(err('gate error: ' + (e && e.message) + ' — FAIL CLOSED: treat as block'));
            }
        }
        default:
            if (id === undefined) return null;             // unknown notification
            return fail(-32601, 'method not found: ' + method);
    }
}

function serve() {
    let buffer = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', async (chunk) => {
        buffer += chunk;
        let nl;
        while ((nl = buffer.indexOf('\n')) >= 0) {
            const line = buffer.slice(0, nl).trim();
            buffer = buffer.slice(nl + 1);
            if (!line) continue;
            let msg;
            try { msg = JSON.parse(line); } catch { continue; }
            const reply = await handleMessage(msg);
            if (reply) process.stdout.write(JSON.stringify(reply) + '\n');
        }
    });
    process.stdin.on('end', () => process.exit(0));
}

// --------------------------------------------------------------------------- #
// --selftest: exercise the full protocol against a mocked gate API
// --------------------------------------------------------------------------- #
async function selftest() {
    const assert = require('assert');
    const calls = [];
    httpGet = async (path) => {
        calls.push(path);
        if (path.startsWith('/api/guardian/check/EQGOOD')) {
            return { status: 200, json: { advice: 'pass', risk_level: 'low',
                     track_record: { false_negative_rate: { pct: 8.3 } } } };
        }
        if (path.startsWith('/api/guardian/check/EQBAD')) {
            return { status: 200, json: { advice: 'block', risk_level: 'high' } };
        }
        if (path.startsWith('/api/guardian/check/nope')) {
            return { status: 400, json: { detail: 'bad address' } };
        }
        if (path === '/api/guardian/trackrecord') {
            return { status: 200, json: { finalized: 40, recall: { pct: 85.7 } } };
        }
        return { status: 500, json: {} };
    };

    const rpc = async (method, params, id) =>
        handleMessage({ jsonrpc: '2.0', id, method, params });

    // handshake
    const init = await rpc('initialize', { protocolVersion: PROTOCOL_VERSION }, 1);
    assert.strictEqual(init.result.serverInfo.name, 'tongpt-guardian-gate');
    assert.strictEqual(await rpc('notifications/initialized', {}, undefined), null);
    console.log('ok 1: initialize handshake');

    // tools/list
    const list = await rpc('tools/list', {}, 2);
    assert.deepStrictEqual(list.result.tools.map(t => t.name).sort(),
        ['ton_token_safety_check', 'ton_track_record']);
    assert(list.result.tools[0].description.includes('NEVER means safe'));
    console.log('ok 2: tools/list with calibrated descriptions');

    // pass / block round trips
    const good = await rpc('tools/call',
        { name: 'ton_token_safety_check', arguments: { address: 'EQGOOD' } }, 3);
    assert(!good.result.isError);
    assert(JSON.parse(good.result.content[0].text).advice === 'pass');
    const bad = await rpc('tools/call',
        { name: 'ton_token_safety_check', arguments: { address: 'EQBAD' } }, 4);
    assert(JSON.parse(bad.result.content[0].text).advice === 'block');
    console.log('ok 3: safety check pass/block round-trip');

    // error paths: invalid address, missing arg, unknown tool, server error
    const inv = await rpc('tools/call',
        { name: 'ton_token_safety_check', arguments: { address: 'nope' } }, 5);
    assert(inv.result.isError && inv.result.content[0].text.includes('invalid TON address'));
    const noarg = await rpc('tools/call',
        { name: 'ton_token_safety_check', arguments: {} }, 6);
    assert(noarg.result.isError);
    const unk = await rpc('tools/call', { name: 'nope', arguments: {} }, 7);
    assert(unk.result.isError);
    const boom = await rpc('tools/call',
        { name: 'ton_token_safety_check', arguments: { address: 'EQOTHER' + 'A'.repeat(40) } }, 8);
    assert(boom.result.isError && boom.result.content[0].text.includes('FAIL CLOSED'));
    console.log('ok 4: error paths fail closed, never silent-pass');

    // track record
    const tr = await rpc('tools/call', { name: 'ton_track_record', arguments: {} }, 9);
    assert(JSON.parse(tr.result.content[0].text).finalized === 40);
    console.log('ok 5: track record tool');

    // unknown method + ping
    const missing = await rpc('does/not/exist', {}, 10);
    assert(missing.error && missing.error.code === -32601);
    const pong = await rpc('ping', {}, 11);
    assert(pong.result && Object.keys(pong.result).length === 0);
    console.log('ok 6: ping + method-not-found');

    console.log('\nAll guardian-mcp selftests passed ✅');
}

if (process.argv.includes('--selftest')) {
    selftest().catch((e) => { console.error('SELFTEST FAIL:', e.message); process.exit(1); });
} else {
    serve();
}
