// tests/AnchorRegistry.spec.ts — REAL TVM tests for anchor_registry.tolk
// (SPEC-001 Phase 3 acceptance). Unlike the excluded SubscriptionTolk.spec.ts,
// this suite compiles the actual Tolk source with @ton/tolk-js and executes it
// in @ton/sandbox — every assertion runs against real contract bytecode.

import { Blockchain, SandboxContract, TreasuryContract } from '@ton/sandbox';
import { Cell, toNano } from '@ton/core';
import { runTolkCompiler } from '@ton/tolk-js';
import * as fs from 'fs';
import * as path from 'path';
import {
    AnchorRegistry,
    ERR_DAY_ALREADY_SET,
    ERR_NOT_OWNER,
} from '../wrappers/AnchorRegistry';
import '@ton/test-utils';

const DAY = 20_649; // an arbitrary 2026 day index
const ROOT_A = BigInt('0x' + 'a1'.repeat(32));
const ROOT_B = BigInt('0x' + 'b2'.repeat(32));

describe('AnchorRegistry', () => {
    let code: Cell;
    let blockchain: Blockchain;
    let owner: SandboxContract<TreasuryContract>;
    let stranger: SandboxContract<TreasuryContract>;
    let registry: SandboxContract<AnchorRegistry>;

    beforeAll(async () => {
        // ANCHOR_BOC_CACHE lets CI/dev pre-compile once (node scripts or a
        // previous run) and skip the ~10s wasm compile; absent, compile fresh.
        const cache = process.env.ANCHOR_BOC_CACHE;
        if (cache && fs.existsSync(cache)) {
            code = Cell.fromBase64(fs.readFileSync(cache, 'utf-8').trim());
            return;
        }
        const contractPath = path.resolve(
            __dirname,
            '..',
            'tongpt-subscription',
            'contracts',
            'anchor_registry.tolk',
        );
        const result = await runTolkCompiler({
            entrypointFileName: 'anchor_registry.tolk',
            fsReadCallback: (p: string) =>
                fs.readFileSync(
                    p === 'anchor_registry.tolk' ? contractPath : p,
                    'utf-8',
                ),
        });
        if (result.status === 'error') {
            throw new Error(`Tolk compilation failed: ${result.message}`);
        }
        code = Cell.fromBase64(result.codeBoc64);
    });

    beforeEach(async () => {
        blockchain = await Blockchain.create();
        owner = await blockchain.treasury('owner');
        stranger = await blockchain.treasury('stranger');
        registry = blockchain.openContract(
            AnchorRegistry.createFromConfig({ owner: owner.address }, code),
        );
        const deploy = await registry.sendDeploy(owner.getSender(), toNano('0.2'));
        expect(deploy.transactions).toHaveTransaction({
            from: owner.address,
            to: registry.address,
            deploy: true,
            success: true,
        });
    });

    it('owner anchors a root; getRoot/hasRoot round-trip', async () => {
        const res = await registry.sendAnchor(owner.getSender(), toNano('0.05'), {
            dayIndex: DAY,
            root: ROOT_A,
        });
        expect(res.transactions).toHaveTransaction({
            from: owner.address,
            to: registry.address,
            success: true,
        });
        expect(await registry.getRoot(DAY)).toEqual(ROOT_A);
        expect(await registry.getHasRoot(DAY)).toBe(true);
    });

    it('unanchored day reads as 0 / hasRoot false', async () => {
        expect(await registry.getRoot(DAY + 1)).toEqual(0n);
        expect(await registry.getHasRoot(DAY + 1)).toBe(false);
    });

    it('non-owner cannot anchor (exit 102)', async () => {
        const res = await registry.sendAnchor(stranger.getSender(), toNano('0.05'), {
            dayIndex: DAY,
            root: ROOT_A,
        });
        expect(res.transactions).toHaveTransaction({
            from: stranger.address,
            to: registry.address,
            success: false,
            exitCode: ERR_NOT_OWNER,
        });
        expect(await registry.getHasRoot(DAY)).toBe(false);
    });

    it('a day can NEVER be overwritten, even by the owner (exit 103)', async () => {
        await registry.sendAnchor(owner.getSender(), toNano('0.05'), {
            dayIndex: DAY,
            root: ROOT_A,
        });
        const res = await registry.sendAnchor(owner.getSender(), toNano('0.05'), {
            dayIndex: DAY,
            root: ROOT_B,
        });
        expect(res.transactions).toHaveTransaction({
            to: registry.address,
            success: false,
            exitCode: ERR_DAY_ALREADY_SET,
        });
        expect(await registry.getRoot(DAY)).toEqual(ROOT_A); // history intact
    });

    it('missed days can be anchored retroactively, in any order', async () => {
        await registry.sendAnchor(owner.getSender(), toNano('0.05'), {
            dayIndex: DAY + 2,
            root: ROOT_B,
        });
        await registry.sendAnchor(owner.getSender(), toNano('0.05'), {
            dayIndex: DAY, // older day, anchored later
            root: ROOT_A,
        });
        expect(await registry.getRoot(DAY)).toEqual(ROOT_A);
        expect(await registry.getRoot(DAY + 2)).toEqual(ROOT_B);
    });

    it('ChangeOwner: new owner can anchor, old owner is locked out', async () => {
        await registry.sendChangeOwner(owner.getSender(), toNano('0.05'), {
            newOwner: stranger.address,
        });
        expect((await registry.getOwner()).equals(stranger.address)).toBe(true);

        const oldOwner = await registry.sendAnchor(owner.getSender(), toNano('0.05'), {
            dayIndex: DAY,
            root: ROOT_A,
        });
        expect(oldOwner.transactions).toHaveTransaction({
            to: registry.address,
            success: false,
            exitCode: ERR_NOT_OWNER,
        });

        const newOwner = await registry.sendAnchor(stranger.getSender(), toNano('0.05'), {
            dayIndex: DAY,
            root: ROOT_B,
        });
        expect(newOwner.transactions).toHaveTransaction({
            from: stranger.address,
            to: registry.address,
            success: true,
        });
        expect(await registry.getRoot(DAY)).toEqual(ROOT_B);
    });

    it('non-owner cannot change owner (exit 102)', async () => {
        const res = await registry.sendChangeOwner(stranger.getSender(), toNano('0.05'), {
            newOwner: stranger.address,
        });
        expect(res.transactions).toHaveTransaction({
            to: registry.address,
            success: false,
            exitCode: ERR_NOT_OWNER,
        });
        expect((await registry.getOwner()).equals(owner.address)).toBe(true);
    });

    it('unknown non-empty message is rejected; empty top-up is allowed', async () => {
        const garbage = await owner.send({
            to: registry.address,
            value: toNano('0.05'),
            body: (await import('@ton/core')).beginCell().storeUint(0xdeadbeef, 32).endCell(),
        });
        expect(garbage.transactions).toHaveTransaction({
            to: registry.address,
            success: false,
        });
        const topup = await registry.sendDeploy(owner.getSender(), toNano('0.1'));
        expect(topup.transactions).toHaveTransaction({
            to: registry.address,
            success: true,
        });
    });
});
