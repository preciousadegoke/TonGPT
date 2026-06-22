// ============================================================================
//  tests/subscription.test.tolk
//  Integration tests for the Subscription contract, run by `acton test`.
//  Each test name is a backtick get-method; `setup()` gives every test a fresh
//  contract so there is no shared state between cases.
// ============================================================================

import "@acton/emulation/network"   // net.send and the emulated blockchain
import "@acton/emulation/testing"   // testing.treasury, grams, Treasury
import "@acton/testing/expect"      // expect(...).toEqual / toHave...

// `Storage`, `Errors`, and the tier constants live inside the contract file, so
// we import it directly to use them in assertions. (In a multi-file layout you
// would instead import a shared "@contracts/types".)
import "@contracts/subscription"
import "@wrappers/Subscription.gen" // the generated typed wrapper

// Deploy a brand-new account owned by `owner`, belonging to `alice`.
fun setup(): (Subscription, Treasury, Treasury) {
    val owner = testing.treasury("owner");
    val alice = testing.treasury("alice");

    val sub = Subscription.fromStorage(Storage {
        owner:       owner.address,
        subscriber:  alice.address,
        currentTier: 0,
        expiresAt:   0,
        renewals:    0,
        totalPaid:   0,
    });
    val res = sub.deploy(owner.address, { value: grams("0.5") });
    expect(res).toHaveSuccessfulDeploy({ to: sub.address });

    return (sub, owner, alice);
}

get fun `test fresh account is inactive`() {
    val (sub, _, _) = setup();
    expect(sub.isActive()).toEqual(false);
}

get fun `test subscribing to basic activates the account`() {
    val (sub, _, alice) = setup();

    // BASIC == 1. Send well above the 0.5 TON price + reserve.
    val res = sub.sendSubscribe(alice.address, 1, { value: grams("1") });
    expect(res).toHaveAllSuccessfulTxs();

    expect(sub.isActive()).toEqual(true);

    val (tier, _, renewals, _) = sub.subscriptionInfo();
    expect(tier).toEqual(1);
    expect(renewals).toEqual(1);
}

get fun `test underpayment is rejected`() {
    val (sub, _, alice) = setup();

    // 0.2 TON is below the BASIC price, so this must fail and change nothing.
    val res = sub.sendSubscribe(alice.address, 1, { value: grams("0.2") });
    expect(res).toHaveFailedTx({
        from:     alice.address,
        to:       sub.address,
        exitCode: Errors.InsufficientPayment,
    });
    expect(sub.isActive()).toEqual(false);
}

get fun `test non-owner cannot change owner`() {
    val (sub, _, alice) = setup();

    val res = sub.sendChangeOwner(alice.address, alice.address, { value: grams("0.1") });
    expect(res).toHaveFailedTx({
        from:     alice.address,
        to:       sub.address,
        exitCode: Errors.NotOwner,
    });
}

get fun `test owner can change owner`() {
    val (sub, owner, alice) = setup();

    val res = sub.sendChangeOwner(owner.address, alice.address, { value: grams("0.1") });
    expect(res).toHaveSuccessfulTx({ from: owner.address, to: sub.address });
    expect(sub.owner()).toEqual(alice.address);
}
