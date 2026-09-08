# TonGPT — The Category Play
### Response to the "Category-Defining" Challenge Prompt · July 2026

Written as strategist + architect + investor, against the actual 2026 TON landscape. No flattery. Sources at the bottom.

---

## THE ONE THING

**Stop being an AI assistant. Become the trust layer of the TON memecoin economy — and make every verdict a public, timestamped receipt.**

Concretely: the product's atomic unit stops being "an answer in a chat" and becomes a **verdict card** — a shareable, forwardable judgment on a token ("🔴 High risk: dev wallet holds 41%, LP unlocked, 3 sibling deploys rugged") that carries TonGPT's name into every group chat it's dropped into. Three mechanisms, all buildable by one person on the existing stack:

1. **Forward-to-verify.** Forward any shill message, contract address, or token link to TonGPT → instant verdict card. Zero new UI; the safety heuristics already exist in `dexscreener_service.py`. Forwarding is the native gesture of Telegram — the scam pitch and the defense finally live in the same app.
2. **Group Guardian.** Add TonGPT to any memecoin group; it silently watches for contract addresses and replies with a verdict when one appears. This is the feature Solana bots structurally *cannot* copy: Solana's discussion happens on X/Discord while trading happens in Telegram. On TON, everything is Telegram. The bot sits where the crime happens.
3. **The receipts ledger.** Every verdict is timestamped and logged; a daily hash goes on-chain (one tiny Tolk contract, pennies). When a token TonGPT flagged rugs six hours later, that's a provable, unfakeable call. Publish the running score ("flagged 34 of the last 41 rugs before they happened"). A better-funded team can clone the bot in a weekend. **They cannot clone six months of public, on-chain-anchored track record.** That's the moat, and it compounds daily.

Why this beats everything else: it converts the product's biggest cost center (answering questions) into its distribution engine (cards that spread themselves), it builds the only dataset nobody on TON has (labeled token outcomes), and it's the *prerequisite* for the agentic endgame — nobody delegates money to an agent without a track record, and you'll have the only public one on the chain.

---

## THE VERDICT ON THE PREMISE

**"AI assistant on TON" is a me-too premise and would die as one.** The chat-wrapper layer is commodity — Maestro covers 14 chains including TON; Not.Trade already ships a TON-native terminal with sniping, copy-trade, *and* an insider safety panel (top-10 holders, dev wallet movement, LP lock). An assistant that "answers questions about tokens" is a strictly weaker version of what execution bots already bundle for free, monetized by fees you don't collect.

The sharper version: **TonGPT is the radar, not the cockpit.** Not.Trade helps you shoot; nobody on TON tells you reliably what *not* to touch — and TON's tooling gap here is real (Solana has RugCheck, Bubblemaps, GMGN safety scores; TON has fragments). Rug pulls took ~$500M last year with the average rug at ~$510k, honeypots are the growth scam of 2026, and wallet-distribution analysis — exactly what you already compute — is the one signal scammers can't fake. The category to own: **"the rug radar"** — *an antivirus for the Telegram trading floor*. When someone in a TON group asks "is this safe?", the reflexive answer should be "forward it to TonGPT." Default-name status is the whole game.

Keep the AI chat — it's the friendly interface and the memory/personalization work makes it sticky — but it's the wrapping paper, not the gift.

---

## RANKED MOVES (by leverage = impact ÷ solo-founder-effort)

**1. Verdict cards + forward-to-verify + Group Guardian.** *(effort: ~2 weeks — heuristics exist; this is rendering + a group message handler)*
Why it wins: turns every answer into an ad; the free tier stops being a cost and becomes acquisition. Why now: honeypot scams are peaking and TON's safety tooling is embarrassingly thin. Downstream: groups install it → you see every new token the moment it's shilled → your dataset gets better → verdicts get better → more groups install it. That's a real data flywheel, not a slideware one.
*Red team: heuristics will make wrong calls publicly, and one loud false-negative ("TonGPT said it was fine and it rugged") could kill credibility. Survives only with calibrated language — risk levels and named signals, never "safe" — plus a visible accuracy score that includes the misses. Honesty about misses is itself differentiation in crypto.*

**2. The on-chain receipts ledger + public track-record page.** *(effort: ~1 week — you already have Tolk skills and the audit discipline)*
Why it wins: it is the moat. Track record is the one asset that's time-locked — money can't buy back-dated proof. Why now: every "AI alpha" account on X is unaccountable; provable calls are a category-level differentiator. Downstream: it's the trust collateral for move 5 (agentic) and the pitch asset for move 4 (grants).
*Red team: on-chain anchoring is theater if nobody checks it. True — but the *page* ("34/41 rugs flagged early") is the marketing; the chain anchor just makes it unfakeable when challenged. Cheap insurance.*

**3. Reprice around reality; monetize flow, not seats.** *(effort: days)*
$272/month Elite is fantasy. Catizen — a top-grossing mini app — sees ~$12 ARPU; Stars pay out ~$0.009–0.013 each after store fees with a 21-day hold. Subscriptions on a memecoin audience whose chain lost ~87% of daily active wallets from the Dec-2024 peak will not carry this. The execution bots print money on **volume fees** (0.5–1% per swap — how BonkBot/Trojan made tens of millions). Your version: confirmation-based swap deep-links via STON.fi referral/fee-share now, TON Connect transaction requests with spending caps later. Keep one cheap sub tier ($5–10/mo) for memory + watchlist + guardian perks; let whales pay you automatically through flow.
*Red team: routing swaps makes you compete with Not.Trade on their turf. No — you route the *decision*, they route the click. "Scanned by TonGPT → swap via partner" is a partnership surface, not a war.*

**4. TON Foundation leverage — apply as the AI-vertical safety layer.** *(effort: a weekend of writing, with the receipts page as exhibit A)*
TON's grant program now runs tiered **Contenders & Champions** grants with **AI as a named focus vertical**, and the Foundation's core problem is that its consumer chain is scam-ridden — you are building the thing they need to exist. An 18-year-old solo founder from Nigeria shipping the ecosystem's trust layer, building in public, is exactly the story TON Society amplifies (regional programs, hackathons with user-acquisition support). This is founder-arbitrage: a Valley team can't be this story.
*Red team: grants are slow and can become the product. Cap the effort: one Contenders application + one hackathon entry, both reusing the receipts page. Never build *for* the grant.*

**5. The agentic frontier — earn the right, then move.** *(effort: sequenced behind 1–2)*
Where it's heading: x402 crossed 480k active agents and 165M transactions by June 2026 with Google/Visa/AWS/Circle/Anthropic behind the foundation; Coinbase shipped agent-native wallets in February. **TON has no agent story yet.** The obvious-in-hindsight move: the first agent framework where Telegram-native agents pay and transact in TON/Stars — and TonGPT positions as its first, most-trusted agent. What you build *now*: scoped, confirmation-based actions (swap deep-links → TON Connect tx requests with per-day caps), reusing the SEC-001 assertion pattern from the register. What you *don't* build now: autonomous execution. Trust first; autonomy is a withdrawal against the track-record balance.
*Red team: solo + safety-critical + agents is how you reopen ten fix-passes of attack surface. Correct — hence deep-links (user signs in their own wallet, you never touch keys) as the only 90-day agentic surface.*

---

## THE UNCOMFORTABLE TRUTHS

1. **Your last nine audit rounds polished the checkout counter of a store with no foot traffic.** The engineering discipline is genuinely rare — and it's also been a comfortable way to avoid the scarier problem: nobody knows TonGPT exists. Distribution debt now dwarfs tech debt, and only one of them kills you.
2. **The AI is the least defensible thing you own.** It's a rented 8B model behind a prompt. Anyone can have it by Tuesday. The defensible assets are the outcome dataset, the track record, and the group installs — none of which exist yet.
3. **Your pricing says you haven't met your user.** $22.70–$272/month against a $12-ARPU ecosystem, paid in Stars that net you ~$0.009 each after Apple's cut and a 21-day hold. The current pricing page is a conversion killer *and* a credibility tell.
4. **The TON memecoin market may be too small to be the endgame.** Daily active wallets fell ~87% off the tap-to-earn peak before stabilizing (~500k daily addresses). It's a fine *wedge* — thin competition, native surface — but if TON's memecoin economy stays this size, the radar must eventually read other chains or die niche. Build the verdict engine chain-agnostic from day one (it mostly already is — DexScreener is multichain).
5. **"Near launch" has lasted too long.** At 47→40 open register items with zero criticals, every additional pre-launch week is now negative-EV. The register's own verdict is verify-then-go. Go.

---

## THE 90-DAY PLAY

**Days 1–14 — Ship the wedge.** Run the smoke test, launch quietly. Build verdict cards + forward-to-verify (reuse `SafetyReport`; add a card renderer + "Scanned by TonGPT — forward any token to check" footer). Start the **TonGPT Radar channel**: auto-post every new TON pair with its verdict minutes after it appears. The channel is the public demo that never sleeps.

**Days 15–30 — Sit where the crime happens.** Group Guardian mode (aiogram group handler + admin-add flow; privacy mode means admins must add you — that's a feature: installs are endorsements). Receipts ledger + `/track-record` page in the mini-app. Kill the $272 tier; introduce $5–10 Guardian tier. Begin the weekly **Rug Report** on your existing Substack/X — real numbers from your own dataset, the only TON-native one.

**Days 31–60 — Compound.** Outcome tracker (label every scanned token: rugged / alive / mooned — this is the dataset). Daily on-chain hash anchor. Apply to TON **Contenders** grant (AI vertical) and one hackathon, receipts page as the pitch. Pitch STON.fi on "verified by TonGPT" swap deep-links with fee-share.

**Days 61–90 — Convert.** Push Group Guardian to 100 groups (DM admins of every TON memecoin group with your accuracy stats — the cold pitch writes itself: "we flagged X before it rugged; your members saw it 6 hours late"). First B2B conversation: launchpads/DEXs paying for screening API. If the flywheel is turning — cards forwarded, groups installing, channel growing — raise the agentic surface: TON Connect tx requests with caps.

**The 10,000-user math:** 100 groups × avg 500 members seeing verdict cards weekly is a 50,000-person top-of-funnel at $0 CAC. Retention comes from watchlist + memory + guardian utility, all already shipped.

---

## BUILD STATUS (updated as shipped)

**Move 1 is now code, not strategy** *(shipped same day)*:

- `services/verdict.py` — verdict engine: calibrated risk cards (never says "safe"), receipt IDs, append-only JSONL ledger + Redis counters. Built on the existing cached/breaker-protected DexScreener safety heuristics.
- `handlers/verify.py` — `/check` (works as a reply in groups), **forward-to-verify** (any private message containing a TON contract address gets a full card, before GPT sees it), **Group Guardian** (watches groups, compact verdict per new address, atomic per-address cooldown + per-chat rate cap, silent otherwise), `/guardian` setup pitch, `/receipts` public track record.
- Wired into `HANDLER_MODULES` before the GPT catch-all; `/start` and `/help` now lead with the Rug Radar.
- Fixed en route: `SafeRedisClient` was missing `ltrim` (chat histories grew unbounded in Redis — REL-009 in the register).

- `services/radar.py` — **Radar channel poster**: supervised loop discovers new TON pairs (DexScreener search, age-filtered, newest first), claims each atomically (SET NX, 7-day window, bounded in-process fallback), verdicts it through the same engine (so channel posts feed the receipts ledger), and posts cards to `RADAR_CHANNEL_ID` with flood caps (3/cycle, 1.5s spacing). Too-new-to-index pairs get an explicit ⚪ "unindexed = riskiest kind" post — silence would be a gap in the record. `/radar` command points users at the channel. **To go live: create the channel, add the bot as admin, set `RADAR_CHANNEL_ID` (+ optional `RADAR_CHANNEL_LINK`).**

**Still open from Move 1–2:** outcome tracker (rugged/alive labels — needs a few weeks of ledger data first), on-chain hash anchor, `/track-record` mini-app page. **First live task: watch the Radar channel for a week to measure TON's real new-pair rate — the key blind spot from the confidence section.**

## CONFIDENCE + BLIND SPOTS

**Confidence in THE ONE THING: ~70%.** High confidence that "assistant" is the wrong identity and trust/receipts is the strongest available wedge for *this* founder on *this* chain. The 30% doubt is mostly market-size risk (truth #4), not mechanism risk.

**What I'd want to know that I don't:**
- **TON's new-token launch rate** (new pairs/day). Below ~30/day the Radar channel is quiet and the wedge narrows to guardian duty on existing tokens. Check DexScreener's TON new-pairs feed for a week before committing the channel format.
- **Not.Trade's roadmap.** If they ship an LLM layer over their safety panel, the assistant framing dies instantly (reinforcing the pivot) — but if they ship *receipts*, the moat window closes. Speed matters.
- **TONAPI rate limits at group scale** — 100 groups × every posted contract could need a paid tier or aggressive caching (the breaker/cache layer exists; verify ceilings).
- **Telegram policy** on bots auto-replying to financial content in groups at scale (spam thresholds, not rules, are the real constraint — admin-added bots are largely safe).
- **Real conversion on the current pricing page** — if any users have hit /upgrade and bounced, that's the fastest confirmation of truth #3.

---

### Sources
- TON network state 2026: [Hangryfeed — TON in 2026](https://www.hangryfeed.com/insights/web3/toncoin), [SQ Magazine — Toncoin Statistics 2026](https://sqmagazine.co.uk/toncoin-statistics/), [tr.energy — TON 2026 outlook](https://tr.energy/en/blog/ton-future-outlook-2026/)
- Competitors: [DEXTools — Best TON Trading Bots 2026](https://www.dextools.io/tutorials/best-ton-trading-bots-telegram-sniper-guide-2026), [QuickNode — Top Telegram Trading Bots](https://www.quicknode.com/builders-guide/best/top-10-telegram-trading-bots)
- Agentic: [VaaSBlock — Crypto-AI Agents 2026](https://www.vaasblock.com/news/crypto-ai-agents-onchain-x402-wallet-economy-2026/), [Coinbase — Agentic Wallets](https://www.coinbase.com/developer-platform/discover/launches/agentic-wallets), [crypto.news — x402 explained](https://crypto.news/what-are-ai-agents-in-crypto-agentic-payments-and-x402-explained/)
- Grants: [TON Blog — Champion Grants](https://blog.ton.org/ton-grants), [ton.org/grants](https://ton.org/en/grants), [TON on X — 5 focus verticals incl. AI](https://x.com/ton_blockchain/status/1928372463383290322)
- Monetization: [Merge — TMA monetization 2026](https://merge.rocks/blog/telegram-mini-apps-2026-monetization-guide-how-to-earn-from-telegram-mini-apps), [ExitBid — Telegram bot monetization](https://exitbid.io/blog/telegram-bot-monetization-2026), [OmiSoft — Mini app monetization](https://omisoft.net/blog/how-to-monetize-telegram-mini-app/)
- Scam landscape: [CoinLaw — Rug Pull Statistics 2026](https://coinlaw.io/rug-pull-statistics/), [xbankang — Meme Coin Rug Pulls 2026](https://www.xbankang.com/blogs/anatomy-of-a-meme-coin-rug-pull-in-2026-know-update-now), [Sumsub — Top Crypto Scams 2026](https://sumsub.com/blog/top-crypto-scams/)
