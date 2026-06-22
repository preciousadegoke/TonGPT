import { Blockchain, SandboxContract, TreasuryContract } from '@ton/sandbox';
import { toNano, Cell, beginCell } from '@ton/core';
import { SubscriptionTolk } from '../wrappers/SubscriptionTolk';
import '@ton/test-utils';

// Price Constants matching contract
const PRICE_STARTER = toNano('10');
const PRICE_PRO = toNano('30');
const PRICE_PRO_PLUS = toNano('60');
const PRICE_ELITE = toNano('120');
const DURATION = 2592000n; // 30 days

describe('SubscriptionTolk', () => {
    let blockchain: Blockchain;
    let owner: SandboxContract<TreasuryContract>;
    let user: SandboxContract<TreasuryContract>;
    let contractCode: Cell;
    let contract: SandboxContract<SubscriptionTolk>;

    beforeAll(async () => {
        // In a real Acton environment, the compiler outputs the code cell.
        // For testing purposes in sandbox, we initialize with a mock cell 
        // representing the compiled Tolk TVM bytecode.
        contractCode = new Cell(); 
    });

    beforeEach(async () => {
        blockchain = await Blockchain.create();
        owner = await blockchain.treasury('owner');
        user = await blockchain.treasury('user');

        contract = blockchain.openContract(
            SubscriptionTolk.createFromConfig({ owner: owner.address }, contractCode)
        );

        // Deploy contract
        const deployResult = await contract.sendDeploy(owner.getSender(), toNano('0.1'));
        expect(deployResult.transactions).toHaveTransaction({
            from: owner.address,
            to: contract.address,
            deploy: true,
            success: true,
        });
    });

    // -------------------------------------------------------------------------
    // 1. Basic Payments & Tier Setting
    // -------------------------------------------------------------------------
    describe('Tier Payments', () => {
        it('Starter Tier: 10 TON activates tier 1', async () => {
            const result = await contract.sendPayment(user.getSender(), PRICE_STARTER);
            expect(result.transactions).toHaveTransaction({
                from: user.address,
                to: contract.address,
                success: true,
            });

            const sub = await contract.getSubscription(user.address);
            expect(sub.tier).toBe(1);
            expect(sub.expiresAt).toBeGreaterThan(0n);
        });

        it('Pro Tier: 30 TON activates tier 2', async () => {
            await contract.sendPayment(user.getSender(), PRICE_PRO);
            const sub = await contract.getSubscription(user.address);
            expect(sub.tier).toBe(2);
        });

        it('Pro+ Tier: 60 TON activates tier 3', async () => {
            await contract.sendPayment(user.getSender(), PRICE_PRO_PLUS);
            const sub = await contract.getSubscription(user.address);
            expect(sub.tier).toBe(3);
        });

        it('Elite Tier: 120 TON activates tier 4', async () => {
            await contract.sendPayment(user.getSender(), PRICE_ELITE);
            const sub = await contract.getSubscription(user.address);
            expect(sub.tier).toBe(4);
        });
    });

    // -------------------------------------------------------------------------
    // 2. Subscription Stacking & Tier Upgrade
    // -------------------------------------------------------------------------
    describe('Subscription Stacking', () => {
        it('Renewing active subscription stacks duration', async () => {
            // Pay Starter tier once
            await contract.sendPayment(user.getSender(), PRICE_STARTER);
            const sub1 = await contract.getSubscription(user.address);
            const expiry1 = sub1.expiresAt;

            // Renew immediately
            await contract.sendPayment(user.getSender(), PRICE_STARTER);
            const sub2 = await contract.getSubscription(user.address);
            const expiry2 = sub2.expiresAt;

            // Should stack exactly DURATION (30 days)
            expect(expiry2).toBe(expiry1 + DURATION);
        });

        it('Higher payment upgrades the tier level', async () => {
            await contract.sendPayment(user.getSender(), PRICE_STARTER);
            let sub = await contract.getSubscription(user.address);
            expect(sub.tier).toBe(1);

            // Upgrade to Pro+
            await contract.sendPayment(user.getSender(), PRICE_PRO_PLUS);
            sub = await contract.getSubscription(user.address);
            expect(sub.tier).toBe(3);
        });
    });

    // -------------------------------------------------------------------------
    // 3. Validation & Overpayment Refunds
    // -------------------------------------------------------------------------
    describe('Validation and Refunds', () => {
        it('Rejects payment below Starter tier with code 101', async () => {
            const result = await contract.sendPayment(user.getSender(), toNano('5')); // Starter is 10
            expect(result.transactions).toHaveTransaction({
                from: user.address,
                to: contract.address,
                success: false,
                exitCode: 101,
            });
        });

        it('Refunds overpayment using send mode 64', async () => {
            const balanceBefore = await user.getBalance();

            // Send 15 TON for Starter tier (costs 10 TON)
            const result = await contract.sendPayment(user.getSender(), toNano('15'));

            expect(result.transactions).toHaveTransaction({
                from: user.address,
                to: contract.address,
                success: true,
            });

            // Verify overpayment (5 TON minus small gas) bounced back to user
            expect(result.transactions).toHaveTransaction({
                from: contract.address,
                to: user.address,
                success: true,
            });

            const balanceAfter = await user.getBalance();
            const difference = balanceBefore - balanceAfter;
            // Net loss should be ~10 TON + minor transaction fee
            expect(difference).toBeLessThan(toNano('10.1'));
        });
    });

    // -------------------------------------------------------------------------
    // 4. Gas Savings & Snapshots
    // -------------------------------------------------------------------------
    describe('Gas and Optimization', () => {
        it('Lazy parse: failed payment uses minimal gas on rejection path', async () => {
            // Early reject (underpayment)
            const rejectResult = await contract.sendPayment(user.getSender(), toNano('1'));
            const rejectGas = rejectResult.transactions[1].description.computePhase?.gasUsed || 0n;

            // Successful payment
            const successResult = await contract.sendPayment(user.getSender(), PRICE_STARTER);
            const successGas = successResult.transactions[1].description.computePhase?.gasUsed || 0n;

            // Gas on rejection path must be significantly lower because storage wasn't loaded or parsed
            expect(rejectGas).toBeLessThan(successGas / 2n);
        });

        it('Gas snapshot verification', async () => {
            const result = await contract.sendPayment(user.getSender(), PRICE_STARTER);
            const gasUsed = result.transactions[1].description.computePhase?.gasUsed || 0n;

            // Track gas consumption (for CI check_gas.sh validation)
            console.log(`[GAS_SNAPSHOT] Subscription Payment gas: ${gasUsed}`);
            expect(gasUsed).toBeLessThan(20000n); // Standard Tolk storage write is highly optimized
        });
    });

    // -------------------------------------------------------------------------
    // 5. Bounce Handling
    // -------------------------------------------------------------------------
    describe('Bounce Handling', () => {
        it('Safely ignores bounced messages and returns code 0', async () => {
            const bouncedBody = beginCell().storeUint(0xffffffff, 32).endCell(); // standard bounced header
            
            const result = await blockchain.sendMessage({
                info: {
                    type: 'internal',
                    bounced: true,
                    ihrDisabled: true,
                    bounce: false,
                    value: { coins: toNano('1') },
                    dest: contract.address,
                    src: user.address,
                },
                body: bouncedBody,
            });

            // Must terminate successfully without throwing
            expect(result.transactions).toHaveTransaction({
                to: contract.address,
                success: true,
            });
        });
    });

    // -------------------------------------------------------------------------
    // 6. Owner Withdrawal
    // -------------------------------------------------------------------------
    describe('Owner Withdrawals', () => {
        it('Owner can withdraw accumulated funds', async () => {
            // Fund contract first
            await contract.sendPayment(user.getSender(), PRICE_ELITE);

            const result = await contract.sendWithdraw(owner.getSender(), toNano('0.1'), { amount: toNano('50') });
            expect(result.transactions).toHaveTransaction({
                from: contract.address,
                to: owner.address,
                success: true,
                value: toNano('50'),
            });
        });

        it('Non-owner is rejected with exit code 102', async () => {
            const result = await contract.sendWithdraw(user.getSender(), toNano('0.1'), { amount: toNano('10') });
            expect(result.transactions).toHaveTransaction({
                from: user.address,
                to: contract.address,
                success: false,
                exitCode: 102,
            });
        });

        it('Fails if withdrawal exceeds balance minus MIN_RESERVE with exit code 103', async () => {
            // Try to withdraw 1000 TON from low-balance contract
            const result = await contract.sendWithdraw(owner.getSender(), toNano('0.1'), { amount: toNano('1000') });
            expect(result.transactions).toHaveTransaction({
                from: owner.address,
                to: contract.address,
                success: false,
                exitCode: 103,
            });
        });
    });
});
