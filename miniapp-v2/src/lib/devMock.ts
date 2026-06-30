/**
 * Dev-only preview layer.
 *
 * When you run `vite dev` in a normal browser (i.e. NOT inside Telegram) and the
 * FastAPI backend isn't running, every `/api/*` call would fail with
 * ECONNREFUSED and the app gets stuck on the consent gate. This module returns
 * realistic sample data for those calls so the whole UI is browsable for design
 * work — Home, Pricing, Checkout, Wallet, AI Chat, Activity, all populated.
 *
 * It is gated on `import.meta.env.DEV && !isTelegram`, so it is completely
 * tree-shaken out of production builds and never runs inside a real Telegram
 * client (where the live backend is used). Pure preview sugar — zero prod impact.
 */
import { endpoints } from '@/config';
import { isTelegram } from '@/lib/telegram';

export const DEV_PREVIEW = import.meta.env.DEV && !isTelegram;

/** Sentinel meaning "no mock for this path — fall through to a real fetch". */
export const NO_MOCK = Symbol('no-mock');

const inDays = (n: number) => new Date(Date.now() + n * 864e5).toISOString();

const TRENDING = [
  { name: 'Notcoin', symbol: 'NOT', change: '+12.4%' },
  { name: 'Hamster Kombat', symbol: 'HMSTR', change: '+4.1%' },
  { name: 'Dogs', symbol: 'DOGS', change: '-2.3%' },
  { name: 'Resistance Dog', symbol: 'REDO', change: '+38.7%' },
];

const WHALES = [
  { type: 'Buy', token: 'NOT', wallet: 'EQC…9pQ2', amount: '124,000 TON', time: new Date(Date.now() - 6e5).toISOString() },
  { type: 'Sell', token: 'DOGS', wallet: 'UQA…k3Lr', amount: '88,500 TON', time: new Date(Date.now() - 36e5).toISOString() },
  { type: 'Buy', token: 'HMSTR', wallet: 'EQB…12zX', amount: '47,200 TON', time: new Date(Date.now() - 72e5).toISOString() },
];

const PAYMENTS = [
  { plan: 'Pro', amount: '30 TON', method: 'TON Pay', date: inDays(-12) },
];

/**
 * Map a request to mock data. Returns NO_MOCK if the path should hit the network.
 * Matching ignores query strings so `/subscription/payment-info?plan=Pro` works.
 */
export function getMock(method: string, rawPath: string): unknown {
  const path = rawPath.split('?')[0];
  const m = method.toUpperCase();

  switch (path) {
    case endpoints.consentStatus:
      return { accepted: true }; // skip the consent gate in preview
    case endpoints.recordConsent:
      return {};
    case endpoints.userStatus:
      // Free by default so every Upgrade CTA + the Pricing conversion flow show.
      return { plan: 'Free', expiry: null, is_premium: false };
    case endpoints.referralToken:
      return { token: 'PREVIEW123' };

    case endpoints.memecoins:
    case endpoints.trending:
      return TRENDING;
    case endpoints.whale:
      return WHALES;
    case endpoints.activity:
      return PAYMENTS;
    case '/stats':
      return { members: 10842, signals_24h: 318, upgrades_7d: 47 };

    case endpoints.walletPayload:
      return { payload: 'preview-nonce' };
    case endpoints.walletAuth:
      return {};
    case endpoints.paymentInfo:
      return { address: 'EQAdummyPreviewProjectWalletAddress000000000000000' };
    case endpoints.verifySubscription:
      return { success: true };
    case endpoints.starsInvoice:
      return { invoice_url: '' };

    case endpoints.aiAnalysis:
      return {
        analysis:
          "Preview mode — here's a sample analysis. NOT is showing strengthening on-chain momentum: net whale inflows over the last 6h, rising holder count, and social mentions up ~18%. Liquidity looks healthy. As always, not financial advice.",
      };
    default:
      return m === 'GET' || m === 'POST' ? NO_MOCK : NO_MOCK;
  }
}
