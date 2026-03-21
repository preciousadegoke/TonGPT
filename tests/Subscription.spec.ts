import { Blockchain, SandboxContract, TreasuryContract } from '@ton/sandbox';
import { toNano, fromNano } from '@ton/core';
import { Subscription } from '../wrappers/subscription_Subscription';
import '@ton/test-utils';

// Top-level constants (moved out of contract body)
const TIER_STARTER = 1000000000n;
const TIER_PRO = 5000000000n;
const TIER_WHALE = 20000000000n;
const DURATION = 2592000n;

// ----------------------------------------------------------------------------------------------------
// TonGPT — Subscription Contract Test Suite
// Tests all 5 patched fixes before Mainnet deployment
// Run: npx blueprint test
// ----------------------------------------------------------------------------------------------------

describe('Subscription', () => {
    let blockchain: Blockchain;
    let owner: SandboxContract<TreasuryContract>;
    let user: SandboxContract<TreasuryContract>;
    let contract: SandboxContract<Subscription>;

    // Deploy a fresh contract before every test
    beforeEach(async () => {
        blockchain = await Blockchain.create();
        owner = await blockchain.treasury('owner');
        user = await blockchain.treasury('user');

        contract = blockchain.openContract(
            await Subscription.fromInit(owner.address)
        );

        // Deploy
        const deployResult = await contract.send(
            owner.getSender(),
            { value: toNano('0.1'), bounce: false },
            { $$type: 'Deploy', queryId: 0n }
        );

        expect(deployResult.transactions).toHaveTransaction({
            from: owner.address,
            to: contract.address,
            deploy: true,
            success: true,
        });
    });

    // ------------------------------------------------------------------------------------------------
    // GROUP 1: Valid Payments — all three tiers
    // ------------------------------------------------------------------------------------------------

    describe('Valid payments', () => {

        it('Starter tier: 1 TON activates subscription', async () => {
            const result = await contract.send(
                user.getSender(),
                { value: toNano('1'), bounce: true },
                null
            );

            expect(result.transactions).toHaveTransaction({
                from: user.address,
                to: contract.address,
                success: true,
            });

            // Verify subscription was stored
            const sub = await contract.getGetSubscription(user.address);
            expect(sub).not.toBeNull();
            expect(sub!.tier).toBe(1n);
            expect(sub!.expiresAt).toBeGreaterThan(0n);

            // Verify isActive getter returns true
            const active = await contract.getIsActive(user.address);
            expect(active).toBe(true);
        });

        it('Pro tier: 5 TON activates subscription', async () => {
            const result = await contract.send(
                user.getSender(),
                { value: toNano('5'), bounce: true },
                null
            );

            expect(result.transactions).toHaveTransaction({
                from: user.address,
                to: contract.address,
                success: true,
            });

            const sub = await contract.getGetSubscription(user.address);
            expect(sub).not.toBeNull();
            expect(sub!.tier).toBe(2n);

            const active = await contract.getIsActive(user.address);
            expect(active).toBe(true);
        });

        it('Whale tier: 20 TON activates subscription', async () => {
            const result = await contract.send(
                user.getSender(),
                { value: toNano('20'), bounce: true },
                null
            );

            expect(result.transactions).toHaveTransaction({
                from: user.address,
                to: contract.address,
                success: true,
            });

            const sub = await contract.getGetSubscription(user.address);
            expect(sub).not.toBeNull();
            expect(sub!.tier).toBe(3n);

            const active = await contract.getIsActive(user.address);
            expect(active).toBe(true);
        });

        it('Overpayment above Whale tier is still accepted as Whale', async () => {
            // Range check logic: anything >= 20 TON = Whale tier
            const result = await contract.send(
                user.getSender(),
                { value: toNano('25'), bounce: true },
                null
            );

            expect(result.transactions).toHaveTransaction({
                from: user.address,
                to: contract.address,
                success: true,
            });

            const sub = await contract.getGetSubscription(user.address);
            expect(sub!.tier).toBe(3n);
        });
    });

    // ------------------------------------------------------------------------------------------------
    // GROUP 2: Invalid Payments — bounce/refund behavior (FIX-2)
    // ------------------------------------------------------------------------------------------------

    describe('Invalid payments', () => {

        it('Payment below Starter tier fails with exit code 101', async () => {
            const result = await contract.send(
                user.getSender(),
                { value: toNano('0.5'), bounce: true },
                null
            );

            // Transaction should fail on contract side
            expect(result.transactions).toHaveTransaction({
                from: user.address,
                to: contract.address,
                success: false,
                exitCode: 101,
            });
        });

        it('Failed payment bounces funds back to sender', async () => {
            const balanceBefore = await user.getBalance();

            await contract.send(
                user.getSender(),
                { value: toNano('0.5'), bounce: true },
                null
            );

            // User gets most of their money back (minus bounce fees)
            const balanceAfter = await user.getBalance();
            const loss = balanceBefore - balanceAfter;

            // Loss should be small (just gas fees), not the full 0.5 TON
            // Tolerance: less than 0.05 TON lost to fees
            expect(loss).toBeLessThan(toNano('0.05'));
        });

        it('No subscription stored after failed payment', async () => {
            await contract.send(
                user.getSender(),
                { value: toNano('0.5'), bounce: true },
                null
            );

            // State must not have changed
            const sub = await contract.getGetSubscription(user.address);
            expect(sub).toBeNull();

            const active = await contract.getIsActive(user.address);
            expect(active).toBe(false);
        });

        it('isActive returns false for address with no subscription', async () => {
            const stranger = await blockchain.treasury('stranger');
            const active = await contract.getIsActive(stranger.address);
            expect(active).toBe(false);
        });
    });

    // ------------------------------------------------------------------------------------------------
    // GROUP 3: Subscription Extension — renew preserves days (FIX-3)
    // ------------------------------------------------------------------------------------------------

    describe('Subscription extension', () => {

        it('Renewing active subscription extends from existing expiry, not now', async () => {
            // First subscription
            await contract.send(
                user.getSender(),
                { value: toNano('1'), bounce: true },
                null
            );

            const subFirst = await contract.getGetSubscription(user.address);
            const firstExpiry = subFirst!.expiresAt;

            // Renew immediately
            await contract.send(
                user.getSender(),
                { value: toNano('1'), bounce: true },
                null
            );

            const subSecond = await contract.getGetSubscription(user.address);
            const secondExpiry = subSecond!.expiresAt;

            // New expiry should be firstExpiry + DURATION, not now + DURATION
            // So secondExpiry should be significantly greater than firstExpiry
            // DURATION already defined at top of file
            expect(secondExpiry).toBeGreaterThanOrEqual(firstExpiry + DURATION);
        });

        it('Renewing upgrades tier correctly', async () => {
            // Start on Starter
            await contract.send(
                user.getSender(),
                { value: toNano('1'), bounce: true },
                null
            );

            let sub = await contract.getGetSubscription(user.address);
            expect(sub!.tier).toBe(1n);

            // Upgrade to Pro
            await contract.send(
                user.getSender(),
                { value: toNano('5'), bounce: true },
                null
            );

            sub = await contract.getGetSubscription(user.address);
            expect(sub!.tier).toBe(2n);
        });
    });

    // ------------------------------------------------------------------------------------------------
    // GROUP 4: Owner Withdrawal — correct mode + balance guard (FIX-4)
    // ------------------------------------------------------------------------------------------------

    describe('Owner withdrawal', () => {

        it('Owner can withdraw after contract has balance', async () => {
            // Fund contract with a valid payment first
            await contract.send(
                user.getSender(),
                { value: toNano('5'), bounce: true },
                null
            );

            const ownerBalanceBefore = await owner.getBalance();

            // Withdraw 1 TON
            const result = await contract.send(
                owner.getSender(),
                { value: toNano('0.1'), bounce: false },
                { $$type: 'Withdraw', amount: toNano('1') }
            );

            expect(result.transactions).toHaveTransaction({
                from: contract.address,
                to: owner.address,
                success: true,
            });

            const ownerBalanceAfter = await owner.getBalance();
            // Owner should have received roughly 1 TON (minus small gas)
            expect(ownerBalanceAfter).toBeGreaterThan(ownerBalanceBefore);
        });

        it('Non-owner cannot withdraw', async () => {
            // Fund contract
            await contract.send(
                user.getSender(),
                { value: toNano('5'), bounce: true },
                null
            );

            // Attacker tries to withdraw
            const result = await contract.send(
                user.getSender(),
                { value: toNano('0.1'), bounce: false },
                { $$type: 'Withdraw', amount: toNano('1') }
            );

            expect(result.transactions).toHaveTransaction({
                from: user.address,
                to: contract.address,
                success: false,
                exitCode: 49469, // "Access denied (owner)"
            });
        });

        it('Withdrawal fails if amount exceeds balance minus MIN_RESERVE', async () => {
            // Contract has only deployment funds (~0.1 TON)
            // Try to withdraw more than available minus reserve
            const result = await contract.send(
                owner.getSender(),
                { value: toNano('0.1'), bounce: false },
                { $$type: 'Withdraw', amount: toNano('100') }
            );

            expect(result.transactions).toHaveTransaction({
                from: owner.address,
                to: contract.address,
                success: false,
                exitCode: 54615, // "Insufficient balance"
            });
        });
    });

    // ------------------------------------------------------------------------------------------------
    // GROUP 5: Getters — price() and expiresAt type (FIX-5)
    // ------------------------------------------------------------------------------------------------

    describe('Getters', () => {

        it('price() returns correct values for all tiers', async () => {
            expect(await contract.getPrice(1n)).toBe(TIER_STARTER);
            expect(await contract.getPrice(2n)).toBe(TIER_PRO);
            expect(await contract.getPrice(3n)).toBe(TIER_WHALE);
            expect(await contract.getPrice(0n)).toBe(0n);
            expect(await contract.getPrice(99n)).toBe(0n);
        });

        it('expiresAt is stored as bigint (uint64) — no truncation', async () => {
            await contract.send(
                user.getSender(),
                { value: toNano('1'), bounce: true },
                null
            );

            const sub = await contract.getGetSubscription(user.address);
            expect(sub).not.toBeNull();

            // expiresAt must be a bigint, not a number
            expect(typeof sub!.expiresAt).toBe('bigint');

            // Value must be a reasonable Unix timestamp + 30 days
            // Current time is roughly 1700000000 seconds
            // expiresAt should be around now + 2592000
            expect(sub!.expiresAt).toBeGreaterThan(1700000000n);
        });

        it('getSubscription returns null for unknown address', async () => {
            const stranger = await blockchain.treasury('stranger');
            const sub = await contract.getGetSubscription(stranger.address);
            expect(sub).toBeNull();
        });
    });
});