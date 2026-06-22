// ====================================================================
// TonGPT Subscription Contract — Tolk + Acton (Optimized v1.1)
// ====================================================================

// Tier constants
const TIER_FREE:     uint8 = 0;
const TIER_STARTER:  uint8 = 1;
const TIER_PRO:      uint8 = 2;
const TIER_PRO_PLUS: uint8 = 3;
const TIER_ELITE:    uint8 = 4;

// Prices in nanotons
const PRICE_STARTER:  uint64 = 10_000_000_000;
const PRICE_PRO:      uint64 = 30_000_000_000;
const PRICE_PRO_PLUS: uint64 = 60_000_000_000;
const PRICE_ELITE:    uint64 = 120_000_000_000;

const DURATION_SECS: uint32 = 2_592_000;   // 30 days
const MIN_RESERVE:   uint64 = 50_000_000;  // 0.05 TON safety buffer

struct SubscriptionData {
    tier: uint8;
    expiresAt: uint32;
}

struct Storage {
    owner: address;
    subscriptions: map<address, SubscriptionData>;
}

// ====================================================================
// Storage helpers
// ====================================================================

fun Storage.load(): Storage {
    return Storage.fromCell(contract.getData());
}

fun Storage.save(self) {
    contract.setData(self.toCell());
}

// ====================================================================
// Main message handler
// ====================================================================

fun onInternalMessage(inMsg: InMessage) {
    if (inMsg.isBounced()) {
        return; // Silently accept bounce
    }

    let sender = inMsg.sender;
    let value = inMsg.value;

    // Simple payment (no opcode or opcode 0)
    if (inMsg.body.remainingBits() < 32 || inMsg.body.loadUint(32) == 0) {
        // Early tier & price validation (saves gas on bad payments)
        let (tier, price) = getTierAndPrice(value);
        if (tier == 0) {
            throw(101); // Insufficient payment
        }

        let storage = Storage.load();
        let now = blockchain.now();

        let baseExpiry = now;
        if (let existing = storage.subscriptions.get(sender)) {
            if (existing.expiresAt > now) {
                baseExpiry = existing.expiresAt;
            }
        }

        let newExpiry = baseExpiry + DURATION_SECS;

        storage.subscriptions.set(sender, SubscriptionData {
            tier: tier,
            expiresAt: newExpiry
        });
        storage.save();

        // Overpayment refund (Send Mode 64)
        if (value > price) {
            send(sender, value - price, SendMode.CARRY_ALL_REMAINING_BALANCE);
        }
    } else {
        // Future: owner withdrawal, etc.
        throw(0xffff); // Unknown opcode
    }
}

// Helper
fun getTierAndPrice(value: uint64): (uint8, uint64) {
    if (value >= PRICE_ELITE)    return (TIER_ELITE,    PRICE_ELITE);
    if (value >= PRICE_PRO_PLUS) return (TIER_PRO_PLUS, PRICE_PRO_PLUS);
    if (value >= PRICE_PRO)      return (TIER_PRO,      PRICE_PRO);
    if (value >= PRICE_STARTER)  return (TIER_STARTER,  PRICE_STARTER);
    return (0, 0);
}

// ====================================================================
// Getters
// ====================================================================

get fun getSubscription(user: address): (uint8, uint32, bool) {
    let storage = Storage.load();
    if (let sub = storage.subscriptions.get(user)) {
        let active = sub.expiresAt > blockchain.now();
        return (sub.tier, sub.expiresAt, active);
    }
    return (TIER_FREE, 0, false);
}

get fun getTierPrice(tier: uint8): uint64 {
    match (tier) {
        TIER_STARTER  => PRICE_STARTER,
        TIER_PRO      => PRICE_PRO,
        TIER_PRO_PLUS => PRICE_PRO_PLUS,
        TIER_ELITE    => PRICE_ELITE,
        _             => 0,
    }
}