import { Address, beginCell, Cell, Contract, contractAddress, ContractProvider, Sender, SendMode } from '@ton/core';

export type SubscriptionData = {
    tier: number;
    expiresAt: bigint;
};

export class SubscriptionTolk implements Contract {
    constructor(readonly address: Address, readonly init?: { code: Cell; data: Cell }) { }

    static createFromAddress(address: Address) {
        return new SubscriptionTolk(address);
    }

    static createFromConfig(config: { owner: Address }, code: Cell, workchain = 0) {
        const data = beginCell()
            .storeAddress(config.owner)
            .storeDict(null) // empty map
            .endCell();
        const init = { code, data };
        return new SubscriptionTolk(contractAddress(workchain, init), init);
    }

    async sendDeploy(provider: ContractProvider, via: Sender, value: bigint) {
        await provider.internal(via, {
            value,
            sendMode: SendMode.PAY_GAS_SEPARATELY,
            body: beginCell().endCell(),
        });
    }

    // Simple payment (no body needed)
    async sendPayment(provider: ContractProvider, via: Sender, value: bigint) {
        await provider.internal(via, {
            value,
            sendMode: SendMode.PAY_GAS_SEPARATELY,
            body: beginCell().endCell(),
        });
    }

    async getSubscription(provider: ContractProvider, user: Address): Promise<SubscriptionData> {
        const result = await provider.get('getSubscription', [
            { type: 'slice', cell: beginCell().storeAddress(user).endCell() }
        ]);
        const stack = result.stack;
        return {
            tier: Number(stack.readBigNumber()),
            expiresAt: stack.readBigNumber(),
        };
    }

    async getTierPrice(provider: ContractProvider, tier: number): Promise<bigint> {
        const result = await provider.get('getTierPrice', [
            { type: 'int', value: BigInt(tier) }
        ]);
        return result.stack.readBigNumber();
    }

    async getIsActive(provider: ContractProvider, user: Address): Promise<boolean> {
        const result = await provider.get('isActive', [
            { type: 'slice', cell: beginCell().storeAddress(user).endCell() }
        ]);
        return result.stack.readBoolean();
    }
}