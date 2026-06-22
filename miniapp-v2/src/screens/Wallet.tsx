import { useLocation } from 'preact-iso';
import { useEffect, useState } from 'preact/hooks';
import { ScreenHeader } from '@/components/layout/ScreenHeader';
import { Skeleton } from '@/components/ui/Skeleton';
import { useBackButton } from '@/hooks/useBackButton';
import { wallet, isWalletConnected, toast } from '@/store';
import { connectWallet, disconnectWallet } from '@/lib/tonconnect';
import { fetchTonBalance, tonScanUrl } from '@/lib/balance';
import { shortAddr } from '@/lib/format';
import { env } from '@/config';
import { haptic, openTelegramLink } from '@/lib/telegram';

export default function Wallet() {
  const { route } = useLocation();
  useBackButton(() => route('/'));

  const w = wallet.value;
  const [balance, setBalance] = useState<number | null | undefined>(undefined); // undefined = loading

  useEffect(() => {
    if (!w.address) {
      setBalance(undefined);
      return;
    }
    setBalance(undefined);
    fetchTonBalance(w.address).then(setBalance);
  }, [w.address]);

  const copy = async () => {
    if (!w.friendlyAddress) return;
    try {
      await navigator.clipboard.writeText(w.friendlyAddress);
      haptic.notify('success');
      toast('Address copied', 'success');
    } catch {
      toast('Copy failed', 'error');
    }
  };

  return (
    <div class="screen space-y-5">
      <ScreenHeader title="Wallet" subtitle={`TON ${env.network}`} />

      {isWalletConnected.value ? (
        <>
          {/* Balance hero */}
          <section
            class="card p-5 animate-scale-in"
            style={{ background: 'linear-gradient(135deg, color-mix(in srgb, var(--accent) 20%, var(--surface)), var(--surface))' }}
          >
            <p class="text-hint text-xs uppercase tracking-wider">Balance</p>
            {balance === undefined ? (
              <Skeleton w="8rem" h="2rem" />
            ) : balance === null ? (
              <p class="text-lg font-semibold text-hint">Unavailable</p>
            ) : (
              <p class="text-3xl font-bold tabular-nums">
                {balance.toFixed(2)} <span class="text-base font-medium text-hint">TON</span>
              </p>
            )}

            <div class="mt-4 flex items-center gap-3">
              <div class="w-10 h-10 rounded-2xl bg-accent/20 grid place-items-center text-xl">👛</div>
              <div class="min-w-0 flex-1">
                <p class="font-semibold text-sm truncate">{w.appName ?? 'TON Wallet'}</p>
                <button class="text-hint text-xs font-mono flex items-center gap-1.5" onClick={copy}>
                  {shortAddr(w.friendlyAddress, 6, 6)}
                  <span class="text-accent font-sans font-semibold">Copy</span>
                </button>
              </div>
            </div>
          </section>

          {/* ton_proof verification status — clearly explained */}
          <section class={`card p-4 ${w.authed ? 'border-positive/40' : 'border-gold/40'}`}>
            <div class="flex items-center gap-2">
              <span class={w.authed ? 'text-positive' : 'text-gold'}>{w.authed ? '🛡️' : '⚠️'}</span>
              <p class="font-semibold text-sm">
                {w.authed ? 'Ownership verified' : 'Ownership not verified'}
              </p>
            </div>
            <p class="text-hint text-xs mt-1.5 leading-relaxed">
              {w.authed
                ? 'You signed a ton_proof challenge, so the backend knows this wallet is really yours. Payments and on-chain features are unlocked.'
                : 'This wallet is connected but didn’t complete the ton_proof signature. Reconnect to sign it — it only proves ownership and never touches your funds.'}
            </p>
            {!w.authed && (
              <button class="btn-ghost w-full mt-3 py-2 text-sm" onClick={() => connectWallet()}>
                Reconnect & verify
              </button>
            )}
          </section>

          {/* Actions */}
          <div class="card divide-y divide-border">
            <button
              class="w-full flex items-center gap-3 p-4 text-left active:bg-surface-2 transition-colors"
              onClick={() => w.address && openTelegramLink(tonScanUrl(w.address))}
            >
              <span class="text-xl">🔎</span>
              <span class="flex-1 font-semibold text-sm">View on Tonscan</span>
              <span class="text-hint">›</span>
            </button>
            <button
              class="w-full flex items-center gap-3 p-4 text-left text-negative active:bg-surface-2 transition-colors"
              onClick={() => { haptic.impact('light'); disconnectWallet(); }}
            >
              <span class="text-xl">⏏️</span>
              <span class="flex-1 font-semibold text-sm">Disconnect</span>
            </button>
          </div>
        </>
      ) : (
        <section class="card p-6 text-center space-y-4 animate-scale-in">
          <div class="text-5xl">🔗</div>
          <div>
            <p class="font-bold text-lg">Connect a TON wallet</p>
            <p class="text-hint text-sm mt-1">
              Tonkeeper, MyTonWallet, Wallet in Telegram & more. We verify ownership with ton_proof — nothing more.
            </p>
          </div>
          <button class="btn-primary w-full" onClick={() => connectWallet()}>Connect Wallet</button>
          <p class="text-hint text-xs">🔐 We never get access to your funds. You approve every transaction.</p>
        </section>
      )}
    </div>
  );
}
