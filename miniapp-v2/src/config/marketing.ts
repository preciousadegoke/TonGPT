/**
 * Marketing / conversion copy, kept separate from pricing logic so non-engineers
 * can tune it. Everything here is designed to be PERSUASIVE BUT HONEST — no fake
 * countdowns, no invented "3 people bought this" tickers. See notes per field.
 */
import type { PlanId } from './index';

/**
 * Optional launch offer. Set `endsAt` to a real ISO date to show an honest
 * countdown ("early-access pricing ends …"). Leave `endsAt` undefined and the
 * UI shows a static "Launch pricing" tag with NO fake timer.
 */
export const LAUNCH_OFFER: { active: boolean; label: string; endsAt?: string } = {
  active: true,
  label: 'Launch pricing',
  endsAt: undefined, // e.g. '2026-07-31T23:59:59Z' — only set if it's truly time-limited
};

/** One-line value prop shown under each tier's price. */
export const VALUE_PROP: Record<PlanId, string> = {
  starter: 'One good call pays for the month.',
  pro: 'Whale + influencer alerts most traders never see.',
  pro_plus: 'Faster signals and deeper filters for active trading.',
  elite: 'Custom AI signals and white-glove support.',
};

/** Trust badges shown near checkout — all are literally true of this app. */
export const TRUST_BADGES: { icon: string; label: string }[] = [
  { icon: '🔐', label: 'Wallet verified with ton_proof' },
  { icon: '⚡', label: 'Instant activation' },
  { icon: '🔁', label: 'No surprise auto-renewal' },
];

/** FAQ — reduces purchase anxiety, which lifts conversion. */
export const PRICING_FAQ: { q: string; a: string }[] = [
  {
    q: 'How do I pay?',
    a: 'Two ways: on-chain with TON from your connected wallet, or instantly with Telegram Stars — no wallet needed for Stars.',
  },
  {
    q: 'What happens when my plan expires?',
    a: 'You simply drop back to Free. Nothing auto-charges — you choose to renew when you want.',
  },
  {
    q: 'Is connecting my wallet safe?',
    a: 'Yes. We use TonConnect with ton_proof, which only verifies you own the wallet. We never get access to your funds and you confirm every transaction in your wallet app.',
  },
  {
    q: 'Can I upgrade later?',
    a: 'Anytime. Pick a higher tier whenever you like — your new features unlock immediately.',
  },
];
