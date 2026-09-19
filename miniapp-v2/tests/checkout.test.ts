import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Address, beginCell, Cell, external, storeMessage } from '@ton/core';
import { CheckoutMachine, type Dependencies, type Ticket } from '../src/lib/checkout-machine';
import { commentBoc, normalizedMessageHash } from '../src/lib/ton-checkout';

const address = '0:' + '11'.repeat(32);
const boc = beginCell().store(storeMessage(external({ to: Address.parse(address), body: beginCell().storeUint(7, 32).endCell() }))).endCell().toBoc().toString('base64');
const ticket: Ticket = { token: 'signed-ticket', reference: 'TGP1-777-pro-abc123', plan: 'pro', rail: 'ton',
  address, sender: address, amount: '30000000000', memo: 'TGP1-777-pro-abc123', network: 'testnet', valid_until: 1_900_000_000 };

function setup(overrides: Partial<Dependencies> = {}) {
  const callbacks: ((status: string) => void)[] = [];
  const deps = {
    network: 'testnet', account: () => ({ address, chain: '-3' }),
    quoteTon: vi.fn().mockResolvedValue(ticket),
    quoteStars: vi.fn().mockResolvedValue({ ...ticket, rail: 'stars', invoice_url: 'https://t.me/$invoice' }),
    sendTransaction: vi.fn().mockResolvedValue({ boc }),
    openInvoice: vi.fn((_url: string, cb: (status: string) => void) => { callbacks.push(cb); }),
    status: vi.fn().mockResolvedValue({ status: 'pending' }), activated: vi.fn(), changed: vi.fn(),
    rejected: (error: unknown) => error === 'rejected', ...overrides,
  };
  return { machine: new CheckoutMachine(deps), deps, callbacks };
}
const flush = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };

describe('explicit upgrades', () => {
  const upgrade: Ticket = { ...ticket, kind: 'upgrade', reference: 'a'.repeat(32),
    memo: 'TGU1-777-pro-' + 'a'.repeat(32), amount: '10000000001', expected_units: 10000000001,
    subscription_expiry: '2030-01-01T00:00:00Z' };
  it.each(['ton', 'stars'] as const)('%s requires review and revalidation before payment', async rail => {
    const quoted = { ...upgrade, rail, invoice_url: rail === 'stars' ? 'https://t.me/$upgrade' : undefined };
    const { machine, deps } = setup({ quoteTon: vi.fn().mockResolvedValue(quoted), quoteStars: vi.fn().mockResolvedValue(quoted), validateQuote: vi.fn().mockResolvedValue({ valid: true }) });
    await machine.start('pro', rail);
    expect(machine.state?.phase).toBe('review');
    expect(deps.sendTransaction).not.toHaveBeenCalled(); expect(deps.openInvoice).not.toHaveBeenCalled();
    await machine.check(); expect(deps.status).not.toHaveBeenCalled();
    await Promise.all([machine.confirmUpgrade(), machine.confirmUpgrade()]);
    if (rail === 'ton') {
      expect(deps.sendTransaction).toHaveBeenCalledTimes(1);
      expect(vi.mocked(deps.sendTransaction).mock.calls[0][0].messages[0]).toEqual({ address, amount: upgrade.amount, payload: commentBoc(upgrade.memo!) });
    } else expect(deps.openInvoice).toHaveBeenCalledTimes(1);
    expect(deps.quoteTon).toHaveBeenCalledTimes(rail === 'ton' ? 1 : 0);
    expect(deps.quoteStars).toHaveBeenCalledTimes(rail === 'stars' ? 1 : 0);
    expect(deps.validateQuote).toHaveBeenCalledWith(quoted);
  });
  it.each(['ton', 'stars'] as const)('%s blocks payment when quote validation fails', async rail => {
    const quoted = { ...upgrade, rail, invoice_url: 'https://t.me/$upgrade' };
    const { machine, deps } = setup({ quoteTon: vi.fn().mockResolvedValue(quoted), quoteStars: vi.fn().mockResolvedValue(quoted), validateQuote: vi.fn().mockRejectedValue(new Error('Subscription changed')) });
    await machine.start('pro', rail); await machine.confirmUpgrade();
    expect(machine.state?.phase).toBe('error');
    expect(deps.sendTransaction).not.toHaveBeenCalled(); expect(deps.openInvoice).not.toHaveBeenCalled();
  });
  it('rejects a changed sending wallet after review', async () => {
    let sender = address;
    const { machine, deps } = setup({ quoteTon: vi.fn().mockResolvedValue(upgrade), account: () => ({ address: sender, chain: '-3' }), validateQuote: vi.fn().mockResolvedValue({}) });
    await machine.start('pro', 'ton'); sender = '0:' + '22'.repeat(32); await machine.confirmUpgrade();
    expect(machine.state?.phase).toBe('error'); expect(deps.sendTransaction).not.toHaveBeenCalled();
  });
  it('does not send after review is dismissed during validation', async () => {
    let finish!: (value: unknown) => void;
    const { machine, deps } = setup({ quoteTon: vi.fn().mockResolvedValue(upgrade), validateQuote: vi.fn(() => new Promise(resolve => { finish = resolve; })) });
    await machine.start('pro', 'ton'); const confirming = machine.confirmUpgrade(); machine.dismiss(); finish({}); await confirming;
    expect(machine.state).toBeNull(); expect(deps.sendTransaction).not.toHaveBeenCalled();
  });
  it.each(['ton', 'stars'] as const)('%s holds mismatches and blocks repayment across restore', async rail => {
    const { machine, deps } = setup({ status: vi.fn().mockResolvedValue({ status: 'reconciliation_required', paymentId: 'held-id' }) });
    machine.restore({ id: 12, plan: 'pro', rail, phase: 'pending', ticket: { ...upgrade, rail }, message: '' });
    await machine.check(); expect(machine.state?.phase).toBe('held'); expect(deps.activated).not.toHaveBeenCalled();
    const saved = machine.state!; machine.restore(saved); machine.dismiss(); await machine.start('elite', rail); machine.reopenInvoice();
    expect(machine.state?.phase).toBe('held'); expect(deps.quoteTon).not.toHaveBeenCalled(); expect(deps.quoteStars).not.toHaveBeenCalled(); expect(deps.openInvoice).not.toHaveBeenCalled();
  });
  it('late invoice cancellation cannot clear a durable hold', async () => {
    const { machine, deps, callbacks } = setup({ status: vi.fn().mockResolvedValue({ status: 'reconciliation_required', paymentId: 'held-id' }) });
    await machine.start('pro', 'stars'); await machine.check(); callbacks[0]('cancelled');
    expect(machine.state?.phase).toBe('held'); await machine.start('elite', 'stars'); expect(deps.quoteStars).toHaveBeenCalledTimes(1);
  });
});

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date('2026-09-14T12:00:00Z')); });
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); });

describe('encoding and transaction lookup', () => {
  it('serializes an actual text-comment cell, preserving the exact monitor memo', () => {
    const encoded = commentBoc(ticket.memo!);
    const slice = Cell.fromBase64(encoded).beginParse();
    expect(slice.loadUint(32)).toBe(0);
    expect(slice.loadStringTail()).toBe(ticket.memo);
    expect(Buffer.from(encoded, 'base64').subarray(0, 4).toString('hex')).toBe('b5ee9c72');
  });
  it('normalizes external messages for lookup without calling their hash a transaction hash', () => {
    const expected = beginCell().storeUint(2, 2).storeUint(0, 2).storeAddress(Address.parse(address))
      .storeUint(0, 4).storeBit(false).storeBit(true).storeRef(beginCell().storeUint(7, 32).endCell()).endCell().hash().toString('hex');
    expect(normalizedMessageHash(boc)).toBe(expected);
    expect(normalizedMessageHash(boc)).not.toBe(boc);
  });
  it('sends the server price/memo and explicitly binds network and sender', async () => {
    const { machine, deps } = setup();
    await machine.start('pro', 'ton');
    expect(deps.sendTransaction).toHaveBeenCalledWith({ network: '-3', from: address, validUntil: ticket.valid_until,
      messages: [{ address, amount: ticket.amount, payload: commentBoc(ticket.memo!) }] });
    expect(deps.status).toHaveBeenCalledWith(ticket, normalizedMessageHash(boc));
    expect(machine.state?.phase).toBe('pending');
    expect(deps.activated).not.toHaveBeenCalled();
  });
});

describe('TON failure boundaries', () => {
  it.each(['backend', 'wallet'])('rejects a %s network mismatch before sending', async (which) => {
    const { machine, deps } = setup(which === 'backend' ? { network: 'mainnet' } : { account: () => ({ address, chain: '-239' }) });
    await machine.start('pro', 'ton');
    expect(machine.state?.phase).toBe('error');
    expect(deps.sendTransaction).not.toHaveBeenCalled();
  });
  it('does not send when the backend refuses a disabled payment path', async () => {
    const { machine, deps } = setup({ quoteTon: vi.fn().mockRejectedValue(new Error('TON disabled')) });
    await machine.start('pro', 'ton');
    expect(machine.state?.phase).toBe('error');
    expect(deps.sendTransaction).not.toHaveBeenCalled();
  });
  it('keeps a submitted payment pending during verification failures and blocks repayment', async () => {
    const { machine, deps } = setup({ status: vi.fn().mockRejectedValue(new Error('Engine unavailable')) });
    await machine.start('pro', 'ton'); await flush();
    expect(machine.state?.phase).toBe('pending');
    expect(machine.state?.message).toContain('Status check failed');
    await machine.start('elite', 'ton');
    expect(deps.sendTransaction).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(125_000);
    expect(machine.state?.phase).toBe('pending');
  });
  it('treats an ambiguous send failure as pending, explicit rejection as cancelled', async () => {
    const first = setup({ sendTransaction: vi.fn().mockRejectedValue(new Error('network error')) });
    await first.machine.start('pro', 'ton');
    expect(first.machine.state?.phase).toBe('pending');
    const second = setup({ sendTransaction: vi.fn().mockRejectedValue('rejected') });
    await second.machine.start('pro', 'ton');
    expect(second.machine.state?.phase).toBe('cancelled');
  });
  it('times out a silent wallet without offering another transfer', async () => {
    const { machine } = setup({ sendTransaction: vi.fn(() => new Promise(() => {})) });
    void machine.start('pro', 'ton'); await flush();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(machine.state?.phase).toBe('pending');
  });
});

describe('Stars and lifecycle', () => {
  it('requires an Engine payment ID and active entitlement after the paid callback', async () => {
    const { machine, deps, callbacks } = setup();
    await machine.start('pro', 'stars'); callbacks[0]('paid'); await flush();
    expect(machine.state?.phase).toBe('pending');
    vi.mocked(deps.status).mockResolvedValue({ status: 'activated', entitlementActive: true, expiry: '2030-01-01T00:00:00Z' });
    await machine.check(); expect(machine.state?.phase).toBe('pending');
    vi.mocked(deps.status).mockResolvedValue({ status: 'activated', paymentId: 'persisted-id', entitlementActive: true, plan: 'Pro', expiry: '2030-01-01T00:00:00Z' });
    await machine.check(); expect(machine.state?.phase).toBe('paid');
    expect(deps.activated).toHaveBeenCalledTimes(1);
  });
  it('fails before opening when invoice URL is missing', async () => {
    const { machine, deps } = setup({ quoteStars: vi.fn().mockResolvedValue({ ...ticket, rail: 'stars' }) });
    await machine.start('pro', 'stars');
    expect(machine.state?.phase).toBe('error'); expect(deps.openInvoice).not.toHaveBeenCalled();
  });
  it('requires Telegram invoice capability before creating an invoice', async () => {
    const { machine, deps } = setup({ openInvoice: undefined });
    await machine.start('pro', 'stars');
    expect(machine.state?.phase).toBe('error'); expect(deps.quoteStars).not.toHaveBeenCalled();
  });
  it('times out a missing callback and reopens the SAME invoice without recreating it', async () => {
    const { machine, deps } = setup();
    await machine.start('pro', 'stars'); await vi.advanceTimersByTimeAsync(60_000);
    expect(machine.state?.phase).toBe('pending');
    machine.reopenInvoice();
    expect(deps.openInvoice).toHaveBeenCalledTimes(2); expect(deps.quoteStars).toHaveBeenCalledTimes(1);
  });
  it('ignores stale callbacks after a cancelled attempt is replaced', async () => {
    const { machine, callbacks } = setup();
    await machine.start('pro', 'stars'); callbacks[0]('cancelled');
    await machine.start('elite', 'stars'); callbacks[0]('paid');
    expect(machine.state?.plan).toBe('elite'); expect(machine.state?.phase).toBe('invoice');
  });
  it('restores pending state and prevents a second payment after reopening', async () => {
    const { machine, deps } = setup();
    machine.restore({ id: 9, plan: 'pro', rail: 'ton', phase: 'wallet', ticket, message: '' });
    machine.dismiss(); await machine.start('elite', 'stars');
    expect(machine.state?.id).toBe(9); expect(deps.quoteStars).not.toHaveBeenCalled();
  });
});
