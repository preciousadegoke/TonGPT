// ============================================================================
//  ⚠️ STATUS (read first) — NOT THE LIVE PAYMENT PATH
//  ----------------------------------------------------------------------------
//  The LIVE TON payment flow is OFF-CHAIN: users send TON to a single monitored
//  wallet with a unique memo, and a backend monitor activates the subscription
//  via the Engine (see services/ton_payments.py + services/engine_client.py
//  complete_payment). That path requires no custom contract and is what the bot
//  uses today.
//
//  This contract is an OPTIONAL, future, fully-on-chain subscription model. It
//  is NOT wired to activation and MUST be re-audited before any mainnet use.
//
//  CANONICAL PRICING (single source of truth: core/pricing.py):
//      Starter  = 10 TON     Pro      = 30 TON
//      Pro+     = 60 TON      Elite    = 120 TON
//  The BASIC/PRO/ENTERPRISE tiers + 0.5/1/2 TON prices below are LEGACY sample
//  values and do NOT match the canonical pricing. Do not deploy this as-is for
//  the marketing tiers; align tiers/prices here first if you revive on-chain
//  subscriptions.
// ============================================================================
//
// ============================================================================
//  TONGPT — subscription.tolk
//  A production-minded subscription payment gateway for TON, written in Tolk.
//
//  WHAT THIS CONTRACT DOES
//  -----------------------
//  One deployed instance represents ONE subscriber's account with a service
//  `owner`. The subscriber sends a `Subscribe { tier }` message together with
//  some TON:
//    1. The contract validates the tier and that enough TON was attached.
//    2. It OPTIMISTICALLY extends the subscription in storage.
//    3. It forwards the tier price to the service `owner` (bounceable).
//    4. It refunds every leftover nanoton to the subscriber (send mode 64).
//  If the forward to the owner bounces, `onBouncedMessage` REVERTS step 2, so
//  a failed payment never leaves the subscriber "subscribed for free".
//
//  Everything lives in this single file on purpose so it is easy to read end to
//  end. In a bigger project you would move the storage/message/error
//  declarations into a shared `types.tolk` and `import` it from both the
//  contract and the tests.
// ============================================================================


// ----------------------------------------------------------------------------
//  1. ERROR CODES
//  `enum Errors` gives every failure a stable exit code. Tests and off-chain
//  tools assert on these numbers, so do not renumber them once you have
//  shipped. 0xFFFF is the conventional "unknown message" code.
// ----------------------------------------------------------------------------
enum Errors {
    InvalidTier         = 100    // tier is not BASIC / PRO / ENTERPRISE
    InsufficientPayment = 101    // attached TON < price + gas reserve
    NotOwner            = 102    // admin action attempted by a non-owner
    InvalidMessage      = 0xFFFF // unknown opcode AND the body is not empty
}


// ----------------------------------------------------------------------------
//  2. TIER CONSTANTS (uint8)
//  Tiers are stored as a single byte. Named constants keep the business logic
//  readable and stop "magic numbers" from leaking everywhere.
// ----------------------------------------------------------------------------
const TIER_NONE:       uint8 = 0    // no active subscription
const TIER_BASIC:      uint8 = 1
const TIER_PRO:        uint8 = 2
const TIER_ENTERPRISE: uint8 = 3

// One billing period = 30 days, in seconds. uint32 is good well past year 2100.
const PERIOD: uint32 = 2592000

// Keep a little TON aside so the two outgoing messages can pay their forward
// fees and still refund the subscriber. 0.05 TON, written in nanotons so the
// value is a plain integer literal (always valid in a `const`).
const MIN_GAS_RESERVE: coins = 50000000   // 0.05 TON


// ----------------------------------------------------------------------------
//  3. PACKED STORAGE
//  Struct fields serialize sequentially into ONE cell. Choosing tight integer
//  widths (uint8 / uint32) keeps the whole struct comfortably under the
//  1023-bit cell limit:
//    owner(267) + subscriber(267) + uint8(8) + uint32(32) + uint32(32)
//    + coins(<=124)  ~= 730 bits  ->  fits in a single cell.
// ----------------------------------------------------------------------------
struct Storage {
    owner:       address    // service provider; receives the subscription fees
    subscriber:  address    // the user this account belongs to
    currentTier: uint8      // TIER_NONE / BASIC / PRO / ENTERPRISE
    expiresAt:   uint32     // unix timestamp when access ends
    renewals:    uint32     // count of successful subscribe / renew cycles
    totalPaid:   coins      // lifetime fees forwarded to the owner
}

// Idiomatic Tolk storage accessors. In `.save()`, `self` is the receiver.
fun Storage.load(): Storage {
    return Storage.fromCell(contract.getData())
}
fun Storage.save(self) {
    contract.setData(self.toCell())
}


// ----------------------------------------------------------------------------
//  4. MESSAGES
//  Each message begins with a unique 32-bit opcode in parentheses. The TVM
//  reads those 4 bytes to route `match` to the correct branch.
// ----------------------------------------------------------------------------

// Sent by the SUBSCRIBER (with TON attached) to buy or renew a tier.
struct (0x5542b5e1) Subscribe {
    tier: uint8
}

// Sent by the OWNER to hand the account over to a new owner address.
struct (0x9a1c0de1) ChangeOwner {
    newOwner: address
}

// Sent BY this contract TO the owner when a fee is collected. Declared here so
// we can re-parse it inside onBouncedMessage if the owner rejects it. The body
// is tiny (32-bit opcode + 8-bit tier = 40 bits), so it fits easily inside the
// 256-bit "Only256BitsOfBody" bounce window.
struct (0x7c8f2a30) FeeNotice {
    tier: uint8
}

// The messages this contract ACCEPTS as fresh incoming traffic.
// (FeeNotice is outgoing-only, so it is deliberately NOT in this union.)
type AllowedMessage = Subscribe | ChangeOwner


// ----------------------------------------------------------------------------
//  5. CONTRACT DECLARATION
//  Ties the storage shape and accepted-message union to the contract, and
//  carries metadata that ends up in the generated ABI.
// ----------------------------------------------------------------------------
contract Subscription {
    author: "TONGPT"
    version: "1.0.0"
    description: "Per-subscriber TON subscription gateway"
    storage: Storage
    incomingMessages: AllowedMessage
}


// ----------------------------------------------------------------------------
//  6. PURE HELPERS
//  Deterministic functions reused by both the handler and the getters. Keeping
//  pricing in one place means the on-chain logic and the off-chain price quote
//  (see priceFor) can never drift apart.
// ----------------------------------------------------------------------------
fun isValidTier(tier: uint8): bool {
    return tier == TIER_BASIC || tier == TIER_PRO || tier == TIER_ENTERPRISE
}

fun tierPrice(tier: uint8): coins {
    if (tier == TIER_BASIC)      { return ton("0.5") }
    if (tier == TIER_PRO)        { return ton("1") }
    if (tier == TIER_ENTERPRISE) { return ton("2") }
    return 0   // unreachable for validated tiers; callers must validate first
}


// ----------------------------------------------------------------------------
//  7. MAIN ENTRYPOINT — onInternalMessage
//  `lazy AllowedMessage.fromSlice(in.body)` parses ON DEMAND: only the fields
//  actually read inside the matched branch are deserialized, which saves gas.
// ----------------------------------------------------------------------------
fun onInternalMessage(in: InMessage) {
    val msg = lazy AllowedMessage.fromSlice(in.body);

    match (msg) {

        // ---- Buy or renew a subscription -----------------------------------
        Subscribe => {
            // 7.1  Validate the request BEFORE touching any state.
            assert (isValidTier(msg.tier)) throw Errors.InvalidTier;

            val price = tierPrice(msg.tier);
            // Require the price PLUS a reserve, so the two sends below can pay
            // their forward fees and still refund the subscriber.
            assert (in.valueCoins >= price + MIN_GAS_RESERVE) throw Errors.InsufficientPayment;

            // 7.2  OPTIMISTIC update: assume the fee forward will succeed.
            //      Renewing never throws away unexpired time — we extend from
            //      whichever is later, the current expiry or "now".
            var storage = lazy Storage.load();
            val current = storage.expiresAt;
            val base = current > blockchain.now() ? current : blockchain.now();
            storage.currentTier = msg.tier;
            storage.expiresAt   = base + PERIOD;
            storage.renewals   += 1;
            storage.totalPaid  += price;
            storage.save();

            // 7.3  Forward the fee to the owner. BounceMode.Only256BitsOfBody
            //      means: if the owner cannot accept it, the first 256 bits of
            //      this body come back to onBouncedMessage so we can revert.
            val notice = createMessage({
                bounce: BounceMode.Only256BitsOfBody,
                value:  price,
                dest:   storage.owner,
                body:   FeeNotice { tier: msg.tier },
            });
            notice.send(SEND_MODE_REGULAR);

            // 7.4  Refund the change. SEND_MODE_CARRY_ALL_REMAINING_MESSAGE_VALUE
            //      (== 64) carries every nanoton still left from THIS inbound
            //      message (after the fee above) back to the subscriber. We OR
            //      in SEND_MODE_IGNORE_ERRORS so a refund hiccup can never abort
            //      the whole transaction. The contract's own balance is left
            //      untouched, so it keeps enough for storage rent.
            val refund = createMessage({
                bounce: BounceMode.NoBounce,   // refunds must never bounce
                value:  0,                     // 0 + mode 64 == "send the leftovers"
                dest:   in.senderAddress,
            });
            refund.send(SEND_MODE_CARRY_ALL_REMAINING_MESSAGE_VALUE | SEND_MODE_IGNORE_ERRORS);
        }

        // ---- Admin: transfer ownership -------------------------------------
        ChangeOwner => {
            var storage = lazy Storage.load();
            assert (in.senderAddress == storage.owner) throw Errors.NotOwner;
            storage.owner = msg.newOwner;
            storage.save();

            // Return the leftover gas of this admin message to the caller, again
            // with send mode 64.
            val ack = createMessage({
                bounce: BounceMode.NoBounce,
                value:  0,
                dest:   in.senderAddress,
            });
            ack.send(SEND_MODE_CARRY_ALL_REMAINING_MESSAGE_VALUE | SEND_MODE_IGNORE_ERRORS);
        }

        // ---- Anything else --------------------------------------------------
        else => {
            // An empty body is a plain top-up (e.g. funding the account) and is
            // allowed. A non-empty unknown body is a caller mistake.
            assert (in.body.isEmpty()) throw Errors.InvalidMessage;
        }
    }
}


// ----------------------------------------------------------------------------
//  8. BOUNCE HANDLER — onBouncedMessage
//  Reached when our bounceable FeeNotice fails on the owner side. We undo the
//  optimistic update from 7.2 so the subscriber is not credited for a payment
//  that never actually landed.
// ----------------------------------------------------------------------------
fun onBouncedMessage(in: InMessageBounced) {
    // Strip the 0xFFFFFFFF bounce marker; the rest is our original FeeNotice.
    in.bouncedBody.skipBouncedPrefix();
    val msg = lazy FeeNotice.fromSlice(in.bouncedBody);

    var storage = lazy Storage.load();

    // Reverse exactly what step 7.2 applied.
    if (storage.renewals > 0) {
        storage.renewals -= 1;
    }
    storage.totalPaid -= tierPrice(msg.tier);
    if (storage.expiresAt >= PERIOD) {
        storage.expiresAt -= PERIOD;          // undoes the `base + PERIOD` extension
    }
    if (storage.renewals == 0) {
        storage.currentTier = TIER_NONE;
    }
    storage.save();
}


// ----------------------------------------------------------------------------
//  9. GETTERS (read-only, callable off-chain for free)
// ----------------------------------------------------------------------------
get fun owner(): address {
    val storage = lazy Storage.load();
    return storage.owner;
}

get fun subscriber(): address {
    val storage = lazy Storage.load();
    return storage.subscriber;
}

// Returns (tier, expiresAt, renewals, totalPaid) in a single call.
get fun subscriptionInfo(): (uint8, uint32, uint32, coins) {
    val storage = lazy Storage.load();
    return (storage.currentTier, storage.expiresAt, storage.renewals, storage.totalPaid);
}

// True while the current period has not yet elapsed.
get fun isActive(): bool {
    val storage = lazy Storage.load();
    return storage.expiresAt > blockchain.now();
}

// Lets a frontend quote a tier price without hard-coding it.
get fun priceFor(tier: uint8): coins {
    return tierPrice(tier);
}
