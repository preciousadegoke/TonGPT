import { useState, useEffect } from 'preact/hooks';
import { Sheet } from '@/components/ui/Sheet';
import { Segmented } from '@/components/ui/Segmented';
import { Icon } from '@/components/ui/Icon';
import { type Plan } from '@/config';
import { TRUST_BADGES } from '@/config/marketing';
import { payWithTon, payWithStars, type CheckoutResult } from '@/lib/payments';
import { isWalletConnected, wallet, toast } from '@/store';
import { connectWallet } from '@/lib/tonconnect';
import { fmtStars, shortAddr } from '@/lib/format';
import { haptic } from '@/lib/telegram';

type Rail = 'ton' | 'stars';
type Phase = 'idle' | 'processing' | 'paid' | 'pending' | 'error';

interface Props {
  plan: Plan | null;
  onClose: () => void;
}

/**
 * Dual-rail checkout. The whole flow is intentionally optimistic:
 *  - We move to "processing" the instant the user commits.
 *  - On a confirmed payment we show a celebratory "paid" state, fire success
 *    haptics, then close.
 *  - On a settling on-chain tx we show "pending" (activating shortly) rather
 *    than blocking — the backend finishes activation out of band.
 *  - On failure we surface a SPECIFIC recovery action, not a dead end.
 */
export function CheckoutSheet({ plan, onClose }: Props) {
  const [rail, setRail] = useState<Rail>('ton');
  const [phase, setPhase] = useState<Phase>('idle');
  const [errMsg, setErrMsg] = useState('');

  // Reset whenever a new plan is opened.
  useEffect(() => {
    if (plan) {
      setPhase('idle');
      setErrMsg('');
      // Default Stars for users with no wallet — fewer steps to convert.
      setRail(isWalletConnected.value ? 'ton' : 'stars');
    }
  }, [plan?.id]);

  if (!plan) return null;

  const settle = (result: CheckoutResult) => {
    switch (result.status) {
      case 'paid':
        setPhase('paid');
        toast(`${plan.name} activated 🎉`, 'success');
        setTimeout(onClose, 1700);
        break;
      case 'pending':
        setPhase('pending');
        toast('Payment received — activating shortly', 'info');
        break;
      case 'cancelled':
        setPhase('idle'); // user backed out; no scary error
        break;
      case 'failed':
        setPhase('error');
        setErrMsg(result.error || 'Something went wrong');
        break;
    }
  };

  const pay = async () => {
    haptic.impact('medium');
    if (rail === 'ton' && !isWalletConnected.value) {
      await connectWallet();
      return; // user returns and taps pay again once connected
    }
    setPhase('processing');
    setErrMsg('');
    const result = rail === 'ton' ? await payWithTon(plan) : await payWithStars(plan);
    settle(result);
  };

  // ── Success state ─────────────────────────────────────────────────────
  if (phase === 'paid') {
    return (
      <Sheet open onClose={onClose} title="">
        <div class="flex flex-col items-center text-center py-7 gap-4">
          <div class="relative">
            <div
              class="w-20 h-20 rounded-full grid place-items-center text-white animate-pop"
              style={{ background: 'var(--positive)', boxShadow: '0 12px 36px -8px color-mix(in srgb, var(--positive) 60%, transparent)' }}
            >
              <Icon name="check" size={40} />
            </div>
            <span class="absolute inset-0 rounded-full ring-4 ring-positive/25 animate-ping" />
          </div>
          <div>
            <h3 class="text-xl font-bold tracking-tight flex items-center justify-center gap-2">
              You&apos;re on {plan.name} <Icon name="crown" size={20} class="text-gold" />
            </h3>
            <p class="text-hint text-sm mt-1">Premium features are unlocked. Happy hunting.</p>
          </div>
        </div>
      </Sheet>
    );
  }

  const railPrice = rail === 'ton' ? `${plan.priceTon} TON` : fmtStars(plan.priceStars);
  const cta =
    phase === 'processing' ? 'Processing…' :
    phase === 'pending' ? 'Activating…' :
    rail === 'ton'
      ? (isWalletConnected.value ? `Pay ${plan.priceTon} TON` : 'Connect wallet to pay')
      : `Pay ${fmtStars(plan.priceStars)}`;

  return (
    <Sheet open={!!plan} onClose={onClose} title={`Upgrade to ${plan.name}`}>
      {/* Rail toggle — animated segmented control */}
      <Segmented<Rail>
        class="mb-4"
        aria-label="Payment method"
        value={rail}
        onChange={setRail}
        options={[
          { value: 'ton', label: 'TON Pay', icon: <Icon name="diamond" size={15} /> },
          { value: 'stars', label: 'Stars', icon: <Icon name="star" size={15} /> },
        ]}
      />

      {/* Order summary */}
      <div class="card-raised p-4 mb-3">
        <div class="flex items-center justify-between">
          <div>
            <p class="font-semibold">{plan.name} · 1 month</p>
            <p class="text-hint text-xs">{plan.tagline}</p>
          </div>
          <p class="text-xl font-bold tabular-nums">{railPrice}</p>
        </div>
        {rail === 'ton' && isWalletConnected.value && (
          <div class="mt-3 pt-3 flex items-center justify-between text-xs" style={{ borderTop: '1px solid var(--hairline)' }}>
            <span class="text-hint">Paying from</span>
            <span class="font-mono flex items-center gap-1.5">
              <span class={wallet.value.authed ? 'text-positive' : 'text-gold'}>●</span>
              {shortAddr(wallet.value.friendlyAddress)}
            </span>
          </div>
        )}
      </div>

      {/* Method explainer */}
      <p class="text-hint text-xs mb-3 leading-relaxed flex items-start gap-2">
        <Icon name={rail === 'ton' ? 'wallet' : 'star'} size={14} class="mt-0.5 shrink-0 text-accent" />
        {rail === 'ton'
          ? 'Paid on-chain from your connected TON wallet. You approve the exact amount in your wallet app — we can’t move funds without you.'
          : 'Paid instantly with Telegram Stars. No wallet required — Telegram handles the charge securely.'}
      </p>

      {/* Inline error with a real recovery action */}
      {phase === 'error' && (
        <div
          class="rounded-2xl p-3.5 mb-3 border text-sm"
          style={{ borderColor: 'color-mix(in srgb, var(--negative) 40%, transparent)', background: 'color-mix(in srgb, var(--negative) 10%, transparent)' }}
        >
          <p class="font-semibold text-negative">Payment didn&apos;t go through</p>
          <p class="text-hint text-xs mt-0.5">{errMsg}</p>
          <div class="flex gap-2 mt-2.5">
            <button class="btn-ghost flex-1 py-2 text-xs" onClick={pay}>
              <Icon name="refresh" size={14} /> Try again
            </button>
            {rail === 'ton' && (
              <button
                class="btn-ghost flex-1 py-2 text-xs"
                onClick={() => { haptic.select(); setRail('stars'); setPhase('idle'); }}
              >
                <Icon name="star" size={14} /> Pay with Stars
              </button>
            )}
          </div>
        </div>
      )}

      <button class="btn-primary w-full" onClick={pay} disabled={phase === 'processing'} aria-busy={phase === 'processing'}>
        {phase === 'processing' ? <Spinner /> : <Icon name="lock" size={16} />}
        {cta}
      </button>

      {/* Compact trust row */}
      <div class="flex items-center justify-center gap-3 mt-3.5 flex-wrap">
        {TRUST_BADGES.map((b) => (
          <span key={b.label} class="text-[11px] text-hint flex items-center gap-1">
            <span>{b.icon}</span>{b.label}
          </span>
        ))}
      </div>
    </Sheet>
  );
}

function Spinner() {
  return <span class="inline-block w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />;
}
