# Acton + Tolk: finishing your `subscription` contract

A step-by-step setup for `~/projects/tongpt/tongpt-subscription` after `acton init`.
Run every command from the **project root** (the folder that holds `Acton.toml`).

---

## Step 1 — Fix / recreate `Acton.toml`

`acton init` writes a minimal manifest. Replace it with a clean one. The three
fields under `[package]` are required, and the `[contracts.Subscription]` key
**must match** the `contract Subscription` name inside the `.tolk` file.

```bash
cat > Acton.toml << 'EOF'
[package]
name        = "tongpt-subscription"
description = "Production-ready TON subscription contract written in Tolk"
version     = "0.1.0"
license     = "MIT"

[contracts.Subscription]
display-name = "TONGPT Subscription"
src          = "contracts/subscription.tolk"

[build]
out-dir = "build"

[test]
include = ["tests/**"]

[import-mappings]
acton     = ".acton"
contracts = "contracts"
tests     = "tests"
wrappers  = "wrappers"
gen       = "gen"
EOF
```

Why these sections:

- **`[package]`** — `name`, `description`, `version` are mandatory; Acton errors without them.
- **`[contracts.Subscription]`** — registers the contract. The key is the contract *name*; `acton wrapper` and `@wrappers/Subscription.gen` derive from it.
- **`[build]`** — `build/Subscription.json` (code BoC + ABI) lands here.
- **`[test]`** — tells the runner where tests live.
- **`[import-mappings]`** — powers `import "@acton/..."`, `@contracts/...`, `@wrappers/...`. A missing `@contracts`/`@wrappers` mapping is the #1 cause of "cannot resolve import" in tests.

> Tip: pin the CLI later with a `[toolchain]` section (`acton = "1.1.0"`) once you
> know your version (`acton --version`). Leave it out for now — a wrong pin makes
> Acton refuse to run.

---

## Step 2 — Create `contracts/` and the contract

```bash
mkdir -p contracts tests
```

Then write `contracts/subscription.tolk` (the full file is in
`subscription.tolk` alongside this guide — copy it in, or paste the
`cat > contracts/subscription.tolk << 'EOF' ... EOF` block from the chat).

What the contract demonstrates:

| Requirement | Where |
|---|---|
| Tier constants as `uint8` | `TIER_NONE/BASIC/PRO/ENTERPRISE` |
| Packed `Storage` struct | section 3, ~730 bits in one cell |
| Lazy parsing | `lazy AllowedMessage.fromSlice(in.body)` |
| Send mode 64 refunds | `SEND_MODE_CARRY_ALL_REMAINING_MESSAGE_VALUE` |
| Getters | `owner / subscriber / subscriptionInfo / isActive / priceFor` |
| Bounce handling | `onBouncedMessage` reverts the optimistic update |

---

## Step 3 — Generate the wrapper, build, test

```bash
acton build               # compile -> build/Subscription.json
acton wrapper Subscription # generate wrappers/Subscription.gen.tolk (needed by tests)
```

Then write `tests/subscription.test.tolk` (full file alongside this guide), and:

```bash
acton test                       # run all tests
acton test --filter "subscrib"   # run a subset by name regex
acton test --snapshot gas.json   # record a GAS SNAPSHOT baseline
```

> The documented gas-snapshot flag is `--snapshot <file>` (not `--gas-snapshot`).
> Commit `gas.json`, then catch regressions later with:
>
> ```bash
> acton test --baseline-snapshot gas.json --fail-on-diff
> ```

Also useful: `acton check` (lint), `acton fmt` (format), `acton test --coverage`,
`acton test --ui` (browse message traces in the browser).

---

## Step 4 — Troubleshooting

**TOML / manifest**
- *"missing field `name`/`description`/`version`"* → fill in all three under `[package]`.
- *"no contracts defined" / nothing builds* → you need a `[contracts.<Name>]` table with a `src`.
- *Wrapper/getters not found in tests* → the `[contracts.X]` key must equal the `contract X` name in the file; regenerate with `acton wrapper X`.
- *TOML parse error* → check for tabs in indentation, smart quotes, or a duplicated `[section]`. Strings need straight double quotes.
- *`src` not found* → path is relative to project root; confirm `contracts/subscription.tolk` exists.

**Compiler (Tolk)**
- *Unresolved `@contracts` / `@wrappers` / `@acton`* → add the mapping in `[import-mappings]`; run `acton wrapper Subscription` so the `.gen` file exists.
- *`blockchain.now()` unknown* → on older Tolk use `now()` instead.
- *Integer type mismatch on `expiresAt`* → wrap the assignment: `storage.expiresAt = (base + PERIOD) as uint32;`.
- *Opcode clash* → every `struct (0x...)` opcode must be unique across the project.

**Tests**
- *Fee forward bounces in a test* → the owner test-wallet rejected the body; this is rare for plain wallets, but if it happens the bounce handler will revert the subscription. Point the fee at a contract that accepts `FeeNotice`, or assert on the bounce.

---

## Step 5 — Verification checklist

- [ ] `Acton.toml` has `[package]` (name/description/version) and `[contracts.Subscription]`.
- [ ] `contracts/subscription.tolk` exists and the `contract Subscription` name matches the manifest key.
- [ ] `acton build` finishes and writes `build/Subscription.json`.
- [ ] `acton wrapper Subscription` created `wrappers/Subscription.gen.tolk`.
- [ ] `acton test` is all green.
- [ ] `acton test --snapshot gas.json` wrote a baseline you commit.
- [ ] `acton check` and `acton fmt --check` are clean.

**Success looks like:** `acton build` reports `Finished`, `acton test` shows
`✓ N passed in 1 file`, and `build/Subscription.json` contains a `code_boc64`
and `hash`. You now have a compiling, tested, gas-baselined subscription
contract ready to deploy to testnet (`acton deploy` / the deploy tutorial).
