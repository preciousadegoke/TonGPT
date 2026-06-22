/**
 * Fetch a wallet's TON balance.
 *
 * Primary: backend proxy GET /api/wallet/balance?address=… → { balance: number }
 * (recommended — keeps any API keys server-side and avoids CORS).
 *
 * Fallback: public toncenter v2 getAddressBalance (nanotons). No key needed for
 * light use; for production add the backend proxy.
 */
import { api } from '@/lib/api';
import { env } from '@/config';

const TON = 1_000_000_000;

export async function fetchTonBalance(address: string): Promise<number | null> {
  // Try the backend proxy first.
  try {
    const r = await api.get<{ balance: number }>(`/wallet/balance?address=${encodeURIComponent(address)}`);
    if (typeof r.balance === 'number') return r.balance;
  } catch {
    /* fall through to public endpoint */
  }

  try {
    const base =
      env.network === 'testnet'
        ? 'https://testnet.toncenter.com/api/v2/getAddressBalance'
        : 'https://toncenter.com/api/v2/getAddressBalance';
    const res = await fetch(`${base}?address=${encodeURIComponent(address)}`);
    if (!res.ok) return null;
    const j = (await res.json()) as { ok: boolean; result: string };
    if (!j.ok) return null;
    return Number(j.result) / TON;
  } catch {
    return null;
  }
}

export function tonScanUrl(address: string) {
  return env.network === 'testnet'
    ? `https://testnet.tonscan.org/address/${address}`
    : `https://tonscan.org/address/${address}`;
}
