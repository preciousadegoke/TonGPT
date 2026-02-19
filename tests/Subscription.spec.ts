import { Blockchain, SandboxContract, TreasuryContract } from '@ton/sandbox';
import { toNano } from '@ton/core';
import { Subscription } from '../wrappers/Subscription';
import '@ton/test-utils';

describe('Subscription', () => {
    let blockchain: Blockchain;
    let deployer: SandboxContract<TreasuryContract>;
    let subscription: SandboxContract<Subscription>;
    let owner: SandboxContract<TreasuryContract>;
    let user: SandboxContract<TreasuryContract>;
    let whale: SandboxContract<TreasuryContract>;

    beforeEach(async () => {
        blockchain = await Blockchain.create();
        owner = await blockchain.treasury('owner');
        user = await blockchain.treasury('user');
        whale = await blockchain.treasury('whale');

        subscription = blockchain.openContract(await Subscription.fromInit(owner.address));

        const deployResult = await subscription.send(
            owner.getSender(),
            { value: toNano('0.05') },
            { $$type: 'Deploy', queryId: 0n }
        );

        expect(deployResult.transactions).toHaveTransaction({
            from: owner.address,
            to: subscription.address,
            deploy: true,
            success: true,
        });
    });

    it('should register STARTER tier for 1 TON', async () => {
        const result = await user.send({
            to: subscription.address,
            value: toNano('1'),
        });

        expect(result.transactions).toHaveTransaction({
            from: user.address,
            to: subscription.address,
            success: true,
        });

        const sub = await subscription.getGetSubscription(user.address);
        expect(sub).not.toBeNull();
        expect(sub!.tier).toEqual(1n); // Tier 1
        expect(sub!.expiresAt).toBeGreaterThan(Math.floor(Date.now() / 1000));
    });

    it('should register WHALE tier for 20 TON', async () => {
        const result = await whale.send({
            to: subscription.address,
            value: toNano('20'),
        });

        expect(result.transactions).toHaveTransaction({
            from: whale.address,
            to: subscription.address,
            success: true,
        });

        const sub = await subscription.getGetSubscription(whale.address);
        expect(sub).not.toBeNull();
        expect(sub!.tier).toEqual(3n); // Tier 3
    });

    it('should REJECT invalid amounts (e.g. 2.5 TON)', async () => {
        const result = await user.send({
            to: subscription.address,
            value: toNano('2.5'),
        });

        expect(result.transactions).toHaveTransaction({
            from: user.address,
            to: subscription.address,
            success: false, // Should bounce
            exitCode: 101, // Custom error code
        });

        const sub = await subscription.getGetSubscription(user.address);
        expect(sub).toBeNull(); // No subscription created
    });
});
