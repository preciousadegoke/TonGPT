import "@stdlib/deploy";
import "./constants.tact";
import "./types.tact";

// ----------------------------------------------------------------------------------------------------
// Smart Contract Logic
// ----------------------------------------------------------------------------------------------------

contract Subscription with Deployable {

    // State Variables
    owner: Address;
    subscriptions: map<Address, SubscriptionData>;

    // Init
    init(owner: Address) {
        self.owner = owner;
    }

    // ------------------------------------------------------------------------------------------------
    // Core Logic: Receive TON -> Route to Tier
    // ------------------------------------------------------------------------------------------------
    receive() {
        let ctx: Context = context();
        let sender: Address = ctx.sender;

        // Range checks against top-level constants (no self. prefix)
        let tier: Int = 0;

        if (ctx.value >= TIER_WHALE) {
            tier = 3;
        } else if (ctx.value >= TIER_PRO) {
            tier = 2;
        } else if (ctx.value >= TIER_STARTER) {
            tier = 1;
        } else {
            throw(101);
        }

        // Extend existing subscription rather than overwriting
        let current_time: Int = now();
        let base_time: Int = current_time;

        let existing: SubscriptionData? = self.subscriptions.get(sender);
        if (existing != null) {
            let existingData: SubscriptionData = existing!!;
            if (existingData.expiresAt > current_time) {
                base_time = existingData.expiresAt;
            }
        }

        let new_expiry: Int = base_time + DURATION;

        self.subscriptions.set(sender, SubscriptionData{
            tier: tier,
            expiresAt: new_expiry
        });
    }

    // ------------------------------------------------------------------------------------------------
    // Admin
    // ------------------------------------------------------------------------------------------------

    receive(msg: Withdraw) {
        require(sender() == self.owner, "Access denied");

        require(
            myBalance() >= msg.amount + MIN_RESERVE,
            "Insufficient balance"
        );

        send(SendParameters{
            to: self.owner,
            value: msg.amount,
            mode: SendIgnoreErrors,
            bounce: false,
            body: "Withdrawal".asComment()
        });
    }

    // ------------------------------------------------------------------------------------------------
    // Getters
    // ------------------------------------------------------------------------------------------------

    get fun getSubscription(user: Address): SubscriptionData? {
        return self.subscriptions.get(user);
    }

    get fun isActive(user: Address): Bool {
        let sub: SubscriptionData? = self.subscriptions.get(user);
        if (sub == null) { return false; }
        let subData: SubscriptionData = sub!!;
        return subData.expiresAt > now();
    }

    get fun price(tier: Int): Int {
        if (tier == 1) { return TIER_STARTER; }
        if (tier == 2) { return TIER_PRO; }
        if (tier == 3) { return TIER_WHALE; }
        return 0;
    }
}