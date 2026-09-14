import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ post: vi.fn(), send: vi.fn(), invoice: vi.fn() }));
vi.mock('../src/lib/api', () => ({ api: { post: mocks.post } }));
vi.mock('../src/lib/tonconnect', () => ({ getTonConnect: () => ({ account: { address: '0:' + '11'.repeat(32), chain: '-3' }, sendTransaction: mocks.send }) }));
vi.mock('@tonconnect/ui', () => ({ UserRejectsError: class extends Error {} }));
vi.mock('../src/config', () => ({ env: { network: 'testnet' } }));
vi.mock('../src/lib/telegram', () => ({ tg: { openInvoice: mocks.invoice }, tgUser: { id: 777 }, haptic: { notify: vi.fn() } }));
vi.mock('../src/store', () => ({ user: { status: { value: null }, loading: { value: true } } }));

beforeEach(() => {
  vi.useFakeTimers(); vi.resetModules(); vi.clearAllMocks();
  vi.stubGlobal('localStorage', { getItem: () => null, setItem: vi.fn() });
});
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it('targets the real TON quote and shared status routes, never the deleted subscription POST', async () => {
  mocks.post.mockImplementation(async (path) => path === '/checkout/ton' ? {
    token: 'signed', reference: 'TGP1-777-pro-abc123', plan: 'pro', rail: 'ton', network: 'testnet',
    address: '0:' + '22'.repeat(32), amount: '30000000000', memo: 'TGP1-777-pro-abc123', valid_until: 1900000000,
  } : { status: 'pending' });
  mocks.send.mockResolvedValue({ boc: 'unparseable-response' });
  const { checkoutMachine } = await import('../src/lib/payments');
  await checkoutMachine.start('pro', 'ton');
  expect(mocks.post).toHaveBeenCalledWith('/checkout/ton', { plan: 'pro', sender: '0:' + '11'.repeat(32) });
  expect(mocks.post).toHaveBeenCalledWith('/checkout/status', { token: 'signed' });
  expect(mocks.post.mock.calls.some(([path]) => path === '/subscription')).toBe(false);
});

it('targets correlated Stars invoice creation and shared status polling after paid', async () => {
  mocks.post.mockImplementation(async (path) => path === '/checkout/stars' ? {
    token: 'signed-stars', reference: 'reference', plan: 'pro', rail: 'stars', invoice_url: 'https://t.me/$sameinvoice',
  } : { status: 'pending' });
  const { checkoutMachine } = await import('../src/lib/payments');
  await checkoutMachine.start('pro', 'stars');
  expect(mocks.post).toHaveBeenCalledWith('/checkout/stars', { plan: 'pro' });
  mocks.invoice.mock.calls[0][1]('paid');
  expect(mocks.post).toHaveBeenCalledWith('/checkout/status', { token: 'signed-stars' });
  expect(checkoutMachine.state?.phase).toBe('pending');
});
