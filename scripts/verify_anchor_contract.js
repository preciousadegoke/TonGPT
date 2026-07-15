// scripts/verify_anchor_contract.js — plain-JS TVM verification of
// anchor_registry.tolk (mirrors tests/AnchorRegistry.spec.ts without jest
// overhead). Run: node scripts/verify_anchor_contract.js
const assert = require('assert');
const fs = require('fs');
const { Blockchain } = require('@ton/sandbox');
const { Cell, beginCell, contractAddress, SendMode } = require('@ton/core');

const OP_ANCHOR = 0x616e6368, OP_CHOWN = 0x9a1c0de1;
const DAY = 20649, ROOT_A = BigInt('0x' + 'a1'.repeat(32)), ROOT_B = BigInt('0x' + 'b2'.repeat(32));

function findTx(res, to, opts = {}) {
  return res.transactions.some(t => {
    const d = t.description;
    if (!t.inMessage || t.inMessage.info.dest?.toString() !== to.toString()) return false;
    const cp = d.computePhase;
    const success = cp?.type === 'vm' ? cp.success && d.actionPhase?.success !== false : true;
    if (opts.success !== undefined && success !== opts.success) return false;
    if (opts.exitCode !== undefined && (cp?.type !== 'vm' || cp.exitCode !== opts.exitCode)) return false;
    return true;
  });
}

(async () => {
  // Compile the real contract source (or use ANCHOR_BOC_CACHE if provided).
  let b64;
  if (process.env.ANCHOR_BOC_CACHE && fs.existsSync(process.env.ANCHOR_BOC_CACHE)) {
    b64 = fs.readFileSync(process.env.ANCHOR_BOC_CACHE, 'utf-8').trim();
  } else {
    const { runTolkCompiler } = require('@ton/tolk-js');
    const path = require('path');
    const cp = path.resolve(__dirname, '..', 'tongpt-subscription', 'contracts', 'anchor_registry.tolk');
    const r = await runTolkCompiler({ entrypointFileName: 'anchor_registry.tolk',
      fsReadCallback: (f) => fs.readFileSync(f === 'anchor_registry.tolk' ? cp : f, 'utf-8') });
    if (r.status === 'error') throw new Error('Tolk compile failed: ' + r.message);
    b64 = r.codeBoc64;
  }
  const code = Cell.fromBase64(b64);
  const bc = await Blockchain.create();
  const owner = await bc.treasury('owner');
  const stranger = await bc.treasury('stranger');

  const data = beginCell().storeAddress(owner.address).storeDict(null).endCell();
  const init = { code, data };
  const addr = contractAddress(0, init);

  let deployed = false;
  const send = (treasury, value, body) => {
    const msg = { to: addr, value, body, sendMode: SendMode.PAY_GAS_SEPARATELY };
    if (!deployed) { msg.init = init; deployed = true; }
    return treasury.send(msg);
  };
  const anchorBody = (day, root) => beginCell().storeUint(OP_ANCHOR, 32).storeUint(day, 32).storeUint(root, 256).endCell();
  const chownBody = (a) => beginCell().storeUint(OP_CHOWN, 32).storeAddress(a).endCell();
  const get = async (name, args = []) => (await bc.runGetMethod(addr, name, args));

  // deploy via empty body top-up
  let r = await send(owner, 200000000n, beginCell().endCell());
  assert(findTx(r, addr, { success: true }), 'deploy/top-up should succeed');

  // 1. owner anchors; getRoot/hasRoot round-trip
  r = await send(owner, 50000000n, anchorBody(DAY, ROOT_A));
  assert(findTx(r, addr, { success: true }), 'owner anchor should succeed');
  let g = await get('getRoot', [{ type: 'int', value: BigInt(DAY) }]);
  assert(g.stackReader.readBigNumber() === ROOT_A, 'getRoot round-trip');
  g = await get('hasRoot', [{ type: 'int', value: BigInt(DAY) }]);
  assert(g.stackReader.readBoolean() === true, 'hasRoot true');
  console.log('ok 1: owner anchors, getRoot/hasRoot round-trip');

  // 2. unanchored day -> 0 / false
  g = await get('getRoot', [{ type: 'int', value: BigInt(DAY + 1) }]);
  assert(g.stackReader.readBigNumber() === 0n, 'missing day reads 0');
  g = await get('hasRoot', [{ type: 'int', value: BigInt(DAY + 1) }]);
  assert(g.stackReader.readBoolean() === false, 'hasRoot false');
  console.log('ok 2: unanchored day reads 0/false');

  // 3. non-owner rejected 102
  r = await send(stranger, 50000000n, anchorBody(DAY + 5, ROOT_B));
  assert(findTx(r, addr, { success: false, exitCode: 102 }), 'stranger anchor must exit 102');
  console.log('ok 3: non-owner anchor rejected (102)');

  // 4. append-only: overwrite rejected 103, history intact
  r = await send(owner, 50000000n, anchorBody(DAY, ROOT_B));
  assert(findTx(r, addr, { success: false, exitCode: 103 }), 'duplicate day must exit 103');
  g = await get('getRoot', [{ type: 'int', value: BigInt(DAY) }]);
  assert(g.stackReader.readBigNumber() === ROOT_A, 'history intact after overwrite attempt');
  console.log('ok 4: append-only — even owner cannot rewrite (103)');

  // 5. retroactive out-of-order anchoring
  r = await send(owner, 50000000n, anchorBody(DAY + 2, ROOT_B));
  assert(findTx(r, addr, { success: true }));
  r = await send(owner, 50000000n, anchorBody(DAY - 3, ROOT_A));
  assert(findTx(r, addr, { success: true }));
  g = await get('getRoot', [{ type: 'int', value: BigInt(DAY - 3) }]);
  assert(g.stackReader.readBigNumber() === ROOT_A);
  console.log('ok 5: retroactive out-of-order anchoring works');

  // 6. ChangeOwner: old locked out, new can anchor
  r = await send(owner, 50000000n, chownBody(stranger.address));
  assert(findTx(r, addr, { success: true }), 'chown should succeed');
  g = await get('getOwner');
  assert(g.stackReader.readAddress().toString() === stranger.address.toString(), 'owner updated');
  r = await send(owner, 50000000n, anchorBody(DAY + 9, ROOT_A));
  assert(findTx(r, addr, { success: false, exitCode: 102 }), 'old owner locked out');
  r = await send(stranger, 50000000n, anchorBody(DAY + 9, ROOT_B));
  assert(findTx(r, addr, { success: true }), 'new owner can anchor');
  console.log('ok 6: ChangeOwner transfers control correctly');

  // 7. non-owner cannot change owner
  r = await send(owner, 50000000n, chownBody(owner.address));
  assert(findTx(r, addr, { success: false, exitCode: 102 }), 'non-owner chown rejected');
  console.log('ok 7: non-owner ChangeOwner rejected (102)');

  // 8. unknown non-empty body rejected; empty top-up allowed
  r = await send(stranger, 50000000n, beginCell().storeUint(0xdeadbeef, 32).endCell());
  assert(findTx(r, addr, { success: false }), 'garbage body rejected');
  r = await send(stranger, 100000000n, beginCell().endCell());
  assert(findTx(r, addr, { success: true }), 'empty top-up allowed from anyone');
  console.log('ok 8: garbage rejected, top-up allowed');

  console.log('\nAll 8 TVM scenarios passed against real anchor_registry.tolk bytecode ✅');
})().catch(e => { console.error('FAIL:', e.message); process.exit(1); });
