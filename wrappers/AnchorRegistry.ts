// wrappers/AnchorRegistry.ts — typed wrapper for anchor_registry.tolk
// (SPEC-001 Phase 3). Mirrors the message/storage layout of the contract.

import {
    Address,
    beginCell,
    Cell,
    Contract,
    contractAddress,
    ContractProvider,
    Sender,
    SendMode,
} from '@ton/core';

export const OP_ANCHOR = 0x616e6368; // "anch"
export const OP_CHANGE_OWNER = 0x9a1c0de1;

export const ERR_NOT_OWNER = 102;
export const ERR_DAY_ALREADY_SET = 103;

export function dayIndexOf(unixSeconds: number): number {
    return Math.floor(unixSeconds / 86400);
}

export class AnchorRegistry implements Contract {
    constructor(readonly address: Address, readonly init?: { code: Cell; data: Cell }) {}

    static createFromAddress(address: Address) {
        return new AnchorRegistry(address);
    }

    /** Storage layout must match struct Storage { owner: address, roots: map }. */
    static createFromConfig(config: { owner: Address }, code: Cell, workchain = 0) {
        const data = beginCell()
            .storeAddress(config.owner)
            .storeDict(null) // empty roots map
            .endCell();
        const init = { code, data };
        return new AnchorRegistry(contractAddress(workchain, init), init);
    }

    async sendDeploy(provider: ContractProvider, via: Sender, value: bigint) {
        await provider.internal(via, {
            value,
            sendMode: SendMode.PAY_GAS_SEPARATELY,
            body: beginCell().endCell(), // empty body = allowed top-up
        });
    }

    async sendAnchor(
        provider: ContractProvider,
        via: Sender,
        value: bigint,
        opts: { dayIndex: number; root: bigint },
    ) {
        await provider.internal(via, {
            value,
            sendMode: SendMode.PAY_GAS_SEPARATELY,
            body: AnchorRegistry.anchorBody(opts.dayIndex, opts.root),
        });
    }

    /** The exact message body an operator wallet must send — also used by the
     *  Python anchor service to build its operator payload. */
    static anchorBody(dayIndex: number, root: bigint): Cell {
        return beginCell()
            .storeUint(OP_ANCHOR, 32)
            .storeUint(dayIndex, 32)
            .storeUint(root, 256)
            .endCell();
    }

    async sendChangeOwner(
        provider: ContractProvider,
        via: Sender,
        value: bigint,
        opts: { newOwner: Address },
    ) {
        await provider.internal(via, {
            value,
            sendMode: SendMode.PAY_GAS_SEPARATELY,
            body: beginCell()
                .storeUint(OP_CHANGE_OWNER, 32)
                .storeAddress(opts.newOwner)
                .endCell(),
        });
    }

    async getRoot(provider: ContractProvider, dayIndex: number): Promise<bigint> {
        const res = await provider.get('getRoot', [
            { type: 'int', value: BigInt(dayIndex) },
        ]);
        return res.stack.readBigNumber();
    }

    async getHasRoot(provider: ContractProvider, dayIndex: number): Promise<boolean> {
        const res = await provider.get('hasRoot', [
            { type: 'int', value: BigInt(dayIndex) },
        ]);
        return res.stack.readBoolean();
    }

    async getOwner(provider: ContractProvider): Promise<Address> {
        const res = await provider.get('getOwner', []);
        return res.stack.readAddress();
    }
}
