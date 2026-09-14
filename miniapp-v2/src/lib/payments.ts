import { signal } from '@preact/signals';
import { UserRejectsError } from '@tonconnect/ui';
import { api } from './api';
import { getTonConnect } from './tonconnect';
import { env } from '@/config';
import { tg, tgUser, haptic } from './telegram';
import { user } from '@/store';
import { CheckoutMachine, type Attempt } from './checkout-machine';

export { isPending } from './checkout-machine';
export type { Rail } from './checkout-machine';
export const checkoutAttempt = signal<Attempt | null>(null);
const storageKey = tgUser?.id ? `tongpt-checkout:${tgUser.id}` : null;

export const checkoutMachine = new CheckoutMachine({
  network: env.network,
  account: () => getTonConnect().account,
  quoteTon: (plan, sender) => api.post('/checkout/ton', { plan, sender }),
  quoteStars: (plan) => api.post('/checkout/stars', { plan }),
  sendTransaction: (request) => getTonConnect().sendTransaction(request),
  openInvoice: tg?.openInvoice?.bind(tg),
  status: (ticket, messageHash) => api.post('/checkout/status', {
    token: ticket.token, ...(messageHash ? { message_hash: messageHash } : {}),
  }),
  rejected: (error) => error instanceof UserRejectsError,
  activated: (result) => {
    user.status.value = { plan: result.plan!, expiry: result.expiry!, is_premium: true };
    user.loading.value = false;
    haptic.notify('success');
  },
  changed: (attempt) => {
    checkoutAttempt.value = attempt;
    if (storageKey) {
      try { localStorage.setItem(storageKey, JSON.stringify(attempt)); } catch { /* retain in-memory state */ }
    }
  },
});
if (storageKey) {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
    if (saved) checkoutMachine.restore(saved);
  } catch { /* no restorable checkout */ }
}
