// scripts/anchor_payload.js — build the Anchor message body for the operator.
//
// The bot computes daily Merkle roots but deliberately holds NO signing key.
// This script turns a (dayIndex, rootHex) pair from the anchor log into the
// exact base64 message body to send to the anchor registry contract from any
// wallet that supports raw message bodies (or a ton:// deep link).
//
// Usage: node scripts/anchor_payload.js <dayIndex> <rootHex> [contractAddress]

const { beginCell } = require('@ton/core');

const [dayIndexArg, rootArg, contractArg] = process.argv.slice(2);
if (!dayIndexArg || !rootArg) {
    console.error('Usage: node scripts/anchor_payload.js <dayIndex> <rootHex> [contractAddress]');
    process.exit(1);
}
const dayIndex = parseInt(dayIndexArg, 10);
const rootHex = rootArg.replace(/^0x/, '').toLowerCase();
if (!Number.isInteger(dayIndex) || dayIndex <= 0 || !/^[0-9a-f]{64}$/.test(rootHex)) {
    console.error('dayIndex must be a positive integer; rootHex must be 64 hex chars.');
    process.exit(1);
}

const OP_ANCHOR = 0x616e6368; // "anch" — must match anchor_registry.tolk
const body = beginCell()
    .storeUint(OP_ANCHOR, 32)
    .storeUint(dayIndex, 32)
    .storeUint(BigInt('0x' + rootHex), 256)
    .endCell();

const b64 = body.toBoc().toString('base64');
console.log('Anchor payload for day', dayIndex, '(' +
    new Date(dayIndex * 86400 * 1000).toISOString().slice(0, 10) + ')');
console.log('root:', rootHex);
console.log('\nmessage body (base64 BOC):\n' + b64);
const contract = contractArg || process.env.ANCHOR_CONTRACT_ADDRESS;
if (contract) {
    const amount = 50000000; // 0.05 TON gas
    console.log('\nton:// deep link:\n' +
        `ton://transfer/${contract}?amount=${amount}&bin=${encodeURIComponent(b64)}`);
} else {
    console.log('\n(no contract address given — pass it as 3rd arg or set ANCHOR_CONTRACT_ADDRESS)');
}
console.log('\nAfter the tx confirms, record it:\n' +
    `  python -c "import asyncio; from services.receipts_anchor import mark_anchored; ` +
    `print(asyncio.run(mark_anchored(${dayIndex}, '<tx-hash>')))"`);
