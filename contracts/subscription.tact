import "@stdlib/deploy";

// ----------------------------------------------------------------------------------------------------
// Structs & Messages
// ----------------------------------------------------------------------------------------------------

struct SubscriptionData {
    tier: Int as uint8;
    expiresAt: Int as uint32;
}

message Withdraw {
    amount: Int as coins;
}

// ----------------------------------------------------------------------------------------------------
// Smart Contract Logic
// ----------------------------------------------------------------------------------------------------

contract Subscription with Deployable {
    
    // State Variables
    owner: Address;
    subscriptions: map<Address, SubscriptionData>; // The On-Chain Ledger

    // Constants (Premium Pricing)
    const TIER_STARTER: Int = 1000000000;  // 1.0 TON
    const TIER_PRO: Int = 5000000000;      // 5.0 TON
    const TIER_WHALE: Int = 20000000000;   // 20.0 TON
    
    const DURATION: Int = 2592000; // 30 Days

    // Init
    init(owner: Address) {
        self.owner = owner;
    }

    // ------------------------------------------------------------------------------------------------
    // Core Logic: Receive TON -> Route to Tier
    // ------------------------------------------------------------------------------------------------
    receive() {
        let ctx: Context = context();
        let amount: Int = ctx.value;
        let sender: Address = ctx.sender;
        
        let tier: Int = 0;

        // Exact Payment Match (Strict)
        if (amount == self.TIER_STARTER) {
            tier = 1;
        } else if (amount == self.TIER_PRO) {
            tier = 2;
        } else if (amount == self.TIER_WHALE) {
            tier = 3;
        } else {
            // Invalid Amount -> Bounce/Refund
            // Exit code 101: Invalid Subscription Amount
            throw(101); 
        }

        // Calculate Expiry
        let current_time: Int = now();
        let new_expiry: Int = current_time + self.DURATION;

        // Check existing subscription to extend (Optional: for now we just overwrite/reset)
        // Future: let existing = self.subscriptions.get(sender); if (existing.expiresAt > now) ...

        // Store State
        self.subscriptions.set(sender, SubscriptionData{
            tier: tier,
            expiresAt: new_expiry
        });

        // Events? 
        // We rely on Getters for state, but emitting events is still good practice for indexers.
        // Tact events are expensive? No, let's keep it pure state for now as requested.
    }

    // ------------------------------------------------------------------------------------------------
    // Admin
    // ------------------------------------------------------------------------------------------------
    
    receive(msg: Withdraw) {
        require(sender() == self.owner, "Access denied");
        send(SendParameters{
            to: self.owner,
            value: msg.amount, 
            mode: SendRemainingValue + SendIgnoreErrors, 
            bounce: false,
            body: "Withdrawal".asComment()
        });
    }

    // ------------------------------------------------------------------------------------------------
    // Getters ("The Source of Truth")
    // ------------------------------------------------------------------------------------------------

    get fun getSubscription(user: Address): SubscriptionData? {
        return self.subscriptions.get(user);
    }

    get fun price(tier: Int): Int {
        if (tier == 1) { return self.TIER_STARTER; }
        if (tier == 2) { return self.TIER_PRO; }
        if (tier == 3) { return self.TIER_WHALE; }
        return 0;
    }
}
