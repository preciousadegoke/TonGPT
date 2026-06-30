/**
 * Central config. Pricing here is the single source of truth for the Mini-App
 * and is kept in lock-step with the bot (handlers/pay.py). If you change tiers,
 * change both places (see README "Plan parity").
 */

export const env = {
  apiBase: import.meta.env.VITE_API_BASE_URL || '/api',
  manifestUrl:
    import.meta.env.VITE_TONCONNECT_MANIFEST_URL ||
    `${location.origin}/tonconnect-manifest.json`,
  network: (import.meta.env.VITE_TON_NETWORK || 'mainnet') as 'mainnet' | 'testnet',
  botUsername: import.meta.env.VITE_BOT_USERNAME || 'TonGpt_bot',
};

export const endpoints = {
  userStatus: '/user/status',
  consentStatus: '/user/consent-status',
  recordConsent: '/user/record-consent',
  referralToken: '/user/referral-token',
  walletPayload: '/wallet/generate-payload',
  walletAuth: '/wallet/auth',
  paymentInfo: '/subscription/payment-info',
  verifySubscription: '/subscription',
  starsInvoice: '/subscription/stars-invoice', // NEW — see README backend section
  memecoins: '/memecoins',
  trending: '/trending',
  scanToken: '/scan-token',
  aiAnalysis: '/ai-analysis',
  whale: '/whale',
  activity: '/user/activity',
} as const;

export type PlanId = 'starter' | 'pro' | 'pro_plus' | 'elite';

export interface Plan {
  id: PlanId;
  name: string;
  tagline: string;
  priceTon: number;
  priceStars: number; // matches handlers/pay.py
  highlight?: boolean;
  badge?: string;
  features: string[];
}

// NOTE: priceTon / priceStars here are DISPLAY values only. The actual charge is
// always minted server-side from core/pricing.py (POST /subscription/stars-invoice),
// so the amount billed is correct even if this list drifts — but a mismatch would
// show the user a price that differs from what they're charged. These values MUST
// therefore equal core/pricing.py exactly. priceStars is the WHOLE number of
// Telegram Stars (XTR has no subunit — never ×100). Ideally fetch these from a
// /subscription/pricing endpoint so there is literally one source.
export const PLANS: Plan[] = [
  {
    id: 'starter',
    name: 'Starter',
    tagline: 'Get the signal',
    priceTon: 10,
    priceStars: 1335,
    features: [
      '100 AI queries / day',
      'Basic market & price alerts',
      'Social sentiment tracking',
      'Email support',
    ],
  },
  {
    id: 'pro',
    name: 'Pro',
    tagline: 'Trade with an edge',
    priceTon: 30,
    priceStars: 4000,
    highlight: true,
    badge: 'Most popular',
    features: [
      '500 AI queries / day',
      'Advanced whale alerts',
      'Portfolio tracking',
      'Custom notifications',
      'Priority support',
    ],
  },
  {
    id: 'pro_plus',
    name: 'Pro+',
    tagline: 'For serious traders',
    priceTon: 60,
    priceStars: 8000,
    features: [
      '1,000 AI queries / day',
      'Real-time market data',
      'Advanced analytics & charts',
      'API access (100 calls / day)',
    ],
  },
  {
    id: 'elite',
    name: 'Elite',
    tagline: 'Maximum alpha',
    priceTon: 120,
    priceStars: 16000,
    badge: 'Whale',
    features: [
      'Unlimited AI queries',
      'VIP whale alerts',
      'Custom API access',
      'Direct developer support',
      '1-on-1 support calls',
    ],
  },
];

export const PLAN_COMPARISON: { label: string; values: (string | boolean)[] }[] = [
  { label: 'AI queries / day', values: ['100', '500', '1,000', '∞'] },
  { label: 'Market & price alerts', values: [true, true, true, true] },
  { label: 'Social sentiment', values: [true, true, true, true] },
  { label: 'Whale alerts', values: [false, 'Advanced', 'Advanced', 'VIP'] },
  { label: 'Portfolio tracking', values: [false, true, true, true] },
  { label: 'Real-time data', values: [false, false, true, true] },
  { label: 'API access', values: [false, false, '100/day', 'Custom'] },
  { label: 'Support', values: ['Email', 'Priority', 'Priority', '1-on-1'] },
];
