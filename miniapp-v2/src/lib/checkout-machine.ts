import { commentBoc, normalizedMessageHash } from './ton-checkout';
import { Address } from '@ton/core';

export type Rail = 'ton' | 'stars';
export type Phase = 'preparing' | 'review' | 'wallet' | 'invoice' | 'pending' | 'held' | 'paid' | 'cancelled' | 'error';
export interface Ticket {
  reference: string; token: string; plan: string; rail: Rail;
  network?: 'mainnet' | 'testnet'; address?: string; sender?: string;
  amount?: string; memo?: string; valid_until?: number; invoice_url?: string;
  kind?: 'upgrade'; expected_units?: number; subscription_expiry?: string;
}
export interface Attempt {
  id: number; plan: string; rail: Rail; phase: Phase; message: string;
  ticket?: Ticket; messageHash?: string; transactionHash?: string; invoicePaid?: boolean;
}
export interface Activation {
  status: 'pending' | 'activated' | 'reconciliation_required'; paymentId?: string; entitlementActive?: boolean;
  plan?: string; expiry?: string; transaction_hash?: string; lookup_error?: string;
}
export interface Dependencies {
  network: string;
  account(): { address: string; chain: string } | null;
  quoteTon(plan: string, sender: string): Promise<Ticket>;
  quoteStars(plan: string): Promise<Ticket>;
  sendTransaction(request: { network: '-3' | '-239'; from: string; validUntil: number;
    messages: { address: string; amount: string; payload: string }[] }): Promise<{ boc: string }>;
  openInvoice?: (url: string, callback: (status: string) => void) => void;
  status(ticket: Ticket, messageHash?: string): Promise<Activation>;
  validateQuote?(ticket: Ticket): Promise<unknown>;
  activated(result: Activation): void;
  changed(attempt: Attempt | null): void;
  rejected(error: unknown): boolean;
}

export const isPending = (attempt: Attempt | null) => !!attempt &&
  ['preparing', 'review', 'wallet', 'invoice', 'pending', 'held'].includes(attempt.phase);

/** One outstanding attempt survives sheet closure; generation IDs reject stale callbacks. */
export class CheckoutMachine {
  state: Attempt | null = null;
  private generation = 0;
  private timer?: ReturnType<typeof setTimeout>;
  private pollTimer?: ReturnType<typeof setTimeout>;
  private polling = false;
  private pollUntil = 0;
  constructor(private deps: Dependencies) {}

  dismiss() {
    if (isPending(this.state) && this.state?.phase !== 'review') return;
    this.clearTimers();
    this.generation++;
    this.state = null;
    this.deps.changed(null);
  }

  restore(saved: Attempt) {
    if (!saved.ticket || !isPending(saved)) return;
    this.generation = saved.id;
    this.state = { ...saved, phase: saved.phase === 'review' || saved.phase === 'held' ? saved.phase : 'pending',
      message: saved.phase === 'review' || saved.phase === 'held' ? saved.message : 'Previous checkout is unconfirmed. Check status before paying again.' };
    this.deps.changed(this.state);
  }
  private update(id: number, patch: Partial<Attempt>) {
    if (this.state?.id !== id || this.state.phase === 'paid') return false;
    // A late wallet/invoice callback must never turn a durable hold into a
    // cancellation or an invitation to pay again. Only reconciliation may resolve it.
    if (this.state.phase === 'held' && patch.phase && !['held', 'paid'].includes(patch.phase)) return false;
    this.state = { ...this.state, ...patch };
    this.deps.changed(this.state);
    return true;
  }
  private clearTimers() { clearTimeout(this.timer); clearTimeout(this.pollTimer); }
  private pending(id: number, message = 'Verifying activation. Do not pay again.') {
    if (!this.update(id, { phase: 'pending', message })) return;
    clearTimeout(this.timer);
    this.pollUntil = Date.now() + 120_000;
    void this.check();
  }
  async confirmUpgrade() {
    const attempt = this.state;
    if (attempt?.phase !== 'review' || !attempt.ticket) return;
    try {
      if (!this.deps.validateQuote) throw new Error('Quote validation unavailable. No payment requested.');
      await this.deps.validateQuote(attempt.ticket);
      if (this.state?.id !== attempt.id || this.state.phase !== 'review') return;
      await this.start(attempt.plan, attempt.rail, attempt.ticket);
    } catch (error) {
      this.update(attempt.id, { phase: 'error', message: (error as Error).message });
    }
  }
  async start(plan: string, rail: Rail, approvedTicket?: Ticket) {
    if (isPending(this.state) && !(approvedTicket && this.state?.phase === 'review' && this.state.ticket === approvedTicket)) return;
    this.clearTimers();
    const id = ++this.generation;
    this.state = { id, plan, rail, phase: 'preparing', message: 'Preparing checkout…' };
    this.deps.changed(this.state);
    try {
      if (rail === 'stars') {
        if (!this.deps.openInvoice) throw new Error('Open this miniapp inside Telegram to pay with Stars.');
        const ticket = approvedTicket || await this.deps.quoteStars(plan);
        if (!ticket.invoice_url || !ticket.token) throw new Error('No invoice was created. Try again.');
        if (!this.update(id, { ticket })) return;
        if (ticket.kind === 'upgrade' && !approvedTicket) {
          this.update(id, { phase: 'review', message: `Review the prorated upgrade. Expiry stays ${ticket.subscription_expiry}.` });
          return;
        }
        this.openStars(id, ticket);
        return;
      }
      const account = this.deps.account();
      if (!account) throw new Error('Connect a wallet first.');
      const ticket = approvedTicket || await this.deps.quoteTon(plan, account.address);
      if (ticket.network !== this.deps.network) throw new Error('Frontend and backend networks differ. Payment was not requested.');
      const chain = ticket.network === 'testnet' ? '-3' : '-239';
      if (account.chain !== chain) throw new Error(`Switch your wallet to ${ticket.network}.`);
      if (ticket.sender && !Address.parse(ticket.sender).equals(Address.parse(account.address)))
        throw new Error('Connected wallet changed. Request a new quote before paying.');
      if (!ticket.address || !ticket.amount || !ticket.memo || !ticket.valid_until || !ticket.token)
        throw new Error('Backend returned an incomplete payment quote.');
      const payload = commentBoc(ticket.memo);
      if (ticket.kind === 'upgrade' && !approvedTicket) {
        this.update(id, { ticket, phase: 'review', message: `Review the prorated upgrade. Expiry stays ${ticket.subscription_expiry}.` });
        return;
      }
      if (!this.update(id, { ticket, phase: 'wallet', message: `Approve the ${ticket.network} transfer in your wallet.` })) return;
      this.timer = setTimeout(() => this.pending(id, 'Wallet confirmation timed out. Check your wallet and status; do not submit another payment.'), 120_000);
      try {
        const result = await this.deps.sendTransaction({ network: chain, from: account.address,
          validUntil: ticket.valid_until, messages: [{ address: ticket.address, amount: ticket.amount, payload }] });
        let messageHash: string | undefined;
        try { messageHash = normalizedMessageHash(result.boc); } catch { /* monitor can still confirm by memo */ }
        if (this.update(id, { messageHash })) this.pending(id);
      } catch (error) {
        if (this.deps.rejected(error)) {
          this.clearTimers();
          this.update(id, { phase: 'cancelled', message: 'Wallet request cancelled.' });
        } else {
          this.pending(id, 'Wallet submission could not be confirmed. Check status; do not pay again.');
        }
      }
    } catch (error) {
      this.update(id, { phase: 'error', message: (error as Error).message || 'Could not start checkout.' });
    }
  }
  private openStars(id: number, ticket: Ticket) {
    if (!this.update(id, { phase: 'invoice', message: 'Complete the invoice in Telegram.' })) return;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.pending(id, 'No invoice result arrived. Check status or reopen this same invoice.'), 60_000);
    let handled = false;
    try {
      this.deps.openInvoice!(ticket.invoice_url!, (status) => {
        if (handled || this.state?.id !== id || this.state.phase === 'paid') return;
        handled = true;
        clearTimeout(this.timer);
        if (status === 'cancelled' || status === 'failed') {
          this.clearTimers();
          this.update(id, { phase: status === 'cancelled' ? 'cancelled' : 'error', message: `Invoice ${status}.` });
        } else {
          this.update(id, { invoicePaid: status === 'paid' });
          this.pending(id);
        }
      });
    } catch {
      this.pending(id, 'Telegram could not confirm that the invoice opened. Check status or reopen the same invoice.');
    }
  }
  reopenInvoice() {
    const current = this.state;
    if (current?.phase === 'pending' && current.rail === 'stars' && !current.invoicePaid && current.ticket?.invoice_url && this.deps.openInvoice)
      this.openStars(current.id, current.ticket);
  }
  async check() {
    const attempt = this.state;
    if (!attempt?.ticket || !isPending(attempt) || attempt.phase === 'review' || this.polling) return;
    const id = attempt.id;
    this.polling = true;
    clearTimeout(this.pollTimer);
    try {
      const result = await this.deps.status(attempt.ticket, attempt.messageHash);
      if (this.state?.id !== id || !isPending(this.state)) return;
      if (result.status === 'reconciliation_required' && result.paymentId) {
        this.clearTimers();
        this.update(id, { phase: 'held', message: `Payment ${result.paymentId} is held for reconciliation. Your plan and expiry were not changed. Contact support; do not pay again.` });
      } else if (result.status === 'activated' && result.paymentId && result.entitlementActive && result.expiry && Date.parse(result.expiry) > Date.now()) {
        this.clearTimers();
        this.update(id, { phase: 'paid', message: 'Engine confirmed activation.', transactionHash: result.transaction_hash });
        this.deps.activated(result);
      } else {
        this.update(id, { transactionHash: result.transaction_hash || this.state.transactionHash,
          message: result.status === 'activated'
            ? 'Payment is recorded, but active entitlement could not be confirmed. Contact support; do not pay again.'
            : result.lookup_error || 'Activation is not confirmed yet. Do not pay again.' });
      }
    } catch (error) {
      this.update(id, { message: `Status check failed: ${(error as Error).message}. Retry status, not payment.` });
    } finally {
      this.polling = false;
      if (this.state?.id === id && this.state.phase === 'pending' && Date.now() < this.pollUntil)
        this.pollTimer = setTimeout(() => void this.check(), 5000);
    }
  }
}
