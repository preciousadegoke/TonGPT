/**
 * Unified checkout for both rails:
 *   • TON Pay  — TonConnect sendTransaction to the project wallet, then backend
 *                verifies the BOC and activates the plan.
 *   • Stars    — backend mints an invoice link (createInvoiceLink), we open it
 *                with Telegram.WebApp.openInvoice and react to the callback.
 *
 * Both return a normalised CheckoutResult so the UI handles success/error once.
 */
import { getTonConnect } from '@/lib/tonconnect';
import { api } from '@/lib/api';
import { endpoints, type Plan } from '@/config';
import { tg, haptic } from '@/lib/telegram';
import { wallet, toast } from '@/store';
import { refreshUserStatus } from '@/lib/user';

export type CheckoutResult =
  | { status: 'paid' }
  | { status: 'pending' }
  | { status: 'cancelled' }
  | { status: 'failed'; error: string };

const TON_DECIMALS = 1_000_000_000;

/** TON Pay via connected wallet. */
export async function payWithTon(plan: Plan): Promise<CheckoutResult> {
  if (!wallet.value.address) return { status: 'failed', error: 'Connect a wallet first' };

  try {
    const { address } = await api.get<{ address: string }>(
      `${endpoints.paymentInfo}?plan=${encodeURIComponent(plan.name)}`,
    );
    // Comment (text payload) lets the backend match the tx to the plan/user.
    const payload = `tongpt:${plan.id}`;
    const tx = {
      validUntil: Math.floor(Date.now() / 1000) + 300,
      messages: [
        {
          address,
          amount: String(Math.round(plan.priceTon * TON_DECIMALS)),
          payload: btoaComment(payload),
        },
      ],
    };

    const result = await getTonConnect().sendTransaction(tx);
    haptic.impact('rigid');

    // Verify the BOC server-side. Activation may be async (pending) while the
    // tx settles — the UI shows an optimistic "Activating…" state for that.
    const v = await api.post<{ success: boolean; pending?: boolean }>(
      endpoints.verifySubscription,
      { wallet_address: wallet.value.address, transaction_hash: result.boc, plan: plan.id },
    );

    if (v.success && !v.pending) {
      await refreshUserStatus();
      haptic.notify('success');
      return { status: 'paid' };
    }
    return { status: 'pending' };
  } catch (e) {
    const msg = (e as Error).message || '';
    if (/reject|cancel|decline/i.test(msg)) {
      haptic.notify('warning');
      return { status: 'cancelled' };
    }
    haptic.notify('error');
    return { status: 'failed', error: 'Transaction failed' };
  }
}

/** Telegram Stars via openInvoice. */
export async function payWithStars(plan: Plan): Promise<CheckoutResult> {
  try {
    const { invoice_url } = await api.post<{ invoice_url: string }>(
      endpoints.starsInvoice,
      { plan: plan.id },
    );

    // No invoice URL (e.g. dev preview, or a misconfigured backend) — don't
    // open a blank tab; surface a pending/no-op state instead.
    if (!invoice_url) return { status: 'pending' };

    if (!tg) {
      window.open(invoice_url, '_blank');
      return { status: 'pending' };
    }

    // Capture into a local const so the narrowing (tg is defined) holds inside
    // the Promise callback closure — TS widens module bindings across closures.
    const webApp = tg;
    return await new Promise<CheckoutResult>((resolve) => {
      webApp.openInvoice(invoice_url, async (status) => {
        if (status === 'paid') {
          await refreshUserStatus();
          haptic.notify('success');
          resolve({ status: 'paid' });
        } else if (status === 'cancelled' || status === 'failed') {
          haptic.notify(status === 'failed' ? 'error' : 'warning');
          resolve(status === 'failed' ? { status: 'failed', error: 'Payment failed' } : { status: 'cancelled' });
        } else {
          resolve({ status: 'pending' });
        }
      });
    });
  } catch {
    toast('Could not start Stars checkout', 'error');
    return { status: 'failed', error: 'Could not create invoice' };
  }
}

/** Encode a short text comment as a base64 cell payload (TEP-74 text comment). */
function btoaComment(text: string): string {
  // 0x00000000 opcode prefix marks a text comment.
  const bytes = new TextEncoder().encode(text);
  const buf = new Uint8Array(4 + bytes.length);
  buf.set([0, 0, 0, 0]);
  buf.set(bytes, 4);
  let bin = '';
  buf.forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin);
}
