// ============================================================================
//  anchor_registry.tolk — TonGPT Receipts Anchor Registry (SPEC-001 Phase 3)
//
//  The smallest possible trust anchor: an append-only map from a UTC day index
//  to the SHA-256 Merkle root of every verdict/outcome receipt TonGPT issued
//  that day. Once a day's root is written it can NEVER be overwritten — so the
//  public track record ("flagged N of the last M rugs early") is provably not
//  back-dated, even by us.
//
//  Deliberate properties:
//    * HOLDS NO FUNDS beyond storage rent, GATES NO product features.
//    * Two ops only: Anchor (owner-gated, append-only) and ChangeOwner.
//    * Attack surface == "can a non-owner write?" and "can a root be
//      overwritten?" — both covered by sandbox tests (AnchorRegistry.spec.ts).
//    * dayIndex = floor(unix_utc / 86400), so missed days can be anchored
//      retroactively in any order without ambiguity.
//
//  Written for Tolk 1.2 (the compiler pinned in package.json via @ton/tolk-js).
// ============================================================================

// ----------------------------------------------------------------------------
//  Error codes (stable — tests assert on these numbers)
// ----------------------------------------------------------------------------
const ERR_NOT_OWNER: int = 102       // Anchor/ChangeOwner from a non-owner
const ERR_DAY_ALREADY_SET: int = 103 // append-only: a day's root is immutable
const ERR_INVALID_MESSAGE: int = 0xFFFF

// ----------------------------------------------------------------------------
//  Storage: owner(267 bits) + roots dict ref — comfortably one cell.
// ----------------------------------------------------------------------------
struct Storage {
    owner: address
    roots: map<uint32, uint256>
}

fun Storage.load(): Storage { return Storage.fromCell(contract.getData()) }
fun Storage.save(self) { contract.setData(self.toCell()) }

// ----------------------------------------------------------------------------
//  Messages. Opcodes are unique 32-bit prefixes ("anch" = 0x616e6368).
// ----------------------------------------------------------------------------
struct (0x616e6368) Anchor {
    dayIndex: uint32     // floor(unix_utc / 86400)
    root: uint256        // SHA-256 Merkle root of the day's receipt hashes
}

struct (0x9a1c0de1) ChangeOwner {
    newOwner: address
}

type AllowedMessage = Anchor | ChangeOwner

// ----------------------------------------------------------------------------
//  Entrypoint
// ----------------------------------------------------------------------------
fun onInternalMessage(in: InMessage) {
    val msg = lazy AllowedMessage.fromSlice(in.body);

    match (msg) {
        Anchor => {
            var storage = lazy Storage.load();
            assert (in.senderAddress == storage.owner) throw ERR_NOT_OWNER;
            // Append-only: a compromised key can write FUTURE days, but can
            // never rewrite history. That is the entire point of this contract.
            assert (!storage.roots.exists(msg.dayIndex)) throw ERR_DAY_ALREADY_SET;
            storage.roots.set(msg.dayIndex, msg.root);
            storage.save();

            // Return leftover gas to the operator wallet.
            val ack = createMessage({
                bounce: BounceMode.NoBounce,
                value: 0,
                dest: in.senderAddress,
            });
            ack.send(SEND_MODE_CARRY_ALL_REMAINING_MESSAGE_VALUE | SEND_MODE_IGNORE_ERRORS);
        }

        ChangeOwner => {
            var storage = lazy Storage.load();
            assert (in.senderAddress == storage.owner) throw ERR_NOT_OWNER;
            storage.owner = msg.newOwner;
            storage.save();

            val ack = createMessage({
                bounce: BounceMode.NoBounce,
                value: 0,
                dest: in.senderAddress,
            });
            ack.send(SEND_MODE_CARRY_ALL_REMAINING_MESSAGE_VALUE | SEND_MODE_IGNORE_ERRORS);
        }

        else => {
            // Empty body = plain top-up for storage rent: allowed.
            assert (in.body.isEmpty()) throw ERR_INVALID_MESSAGE;
        }
    }
}

// ----------------------------------------------------------------------------
//  Getters (free off-chain reads — the public verification surface)
// ----------------------------------------------------------------------------

// Returns the anchored root for a day, or 0 if that day was never anchored.
// (0 is unambiguous: a real SHA-256 Merkle root is never zero in practice,
//  and hasRoot() exists for the pedantic case.)
get fun getRoot(dayIndex: uint32): uint256 {
    val storage = lazy Storage.load();
    val r = storage.roots.get(dayIndex);
    return r.isFound ? r.loadValue() : 0;
}

get fun hasRoot(dayIndex: uint32): bool {
    val storage = lazy Storage.load();
    return storage.roots.exists(dayIndex);
}

get fun getOwner(): address {
    val storage = lazy Storage.load();
    return storage.owner;
}
