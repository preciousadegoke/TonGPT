import { useEffect, useRef, useState } from 'preact/hooks';
import { Sheet } from '@/components/ui/Sheet';
import { Icon } from '@/components/ui/Icon';
import { PLANS, env, type Plan } from '@/config';
import { api } from '@/lib/api';
import { checkoutAttempt, checkoutMachine, isPending, type Rail } from '@/lib/payments';
import { connectWallet } from '@/lib/tonconnect';
import { isWalletConnected, user } from '@/store';
import { fmtStars } from '@/lib/format';

interface Props { plan: Plan | null; onClose: () => void }

export function CheckoutSheet({ plan, onClose }: Props) {
  const [rail, setRail] = useState<Rail>('stars');
  const [tonEnabled, setTonEnabled] = useState(false);
  const [configMessage, setConfigMessage] = useState('Checking TON availability…');
  const [localError, setLocalError] = useState('');
  const generation = useRef(0);
  const attempt = checkoutAttempt.value;
  const busy = isPending(attempt);

  useEffect(() => {
    const id = ++generation.current;
    if (!plan) {
      checkoutMachine.dismiss();
      return;
    }
    setTonEnabled(false);
    setConfigMessage('Checking TON availability…');
    setLocalError('');
    api.get<{ enabled: boolean; network?: string; error?: string }>('/checkout/config')
      .then((config) => {
        if (generation.current !== id) return;
        const enabled = config.enabled && config.network === env.network;
        setTonEnabled(enabled);
        setConfigMessage(enabled ? `TON payments use ${config.network}.`
          : config.error || (config.enabled ? 'Network configuration differs; TON payment is disabled.' : 'TON payment is disabled by the backend.'));
        if (!enabled) setRail('stars');
      }).catch(() => {
        if (generation.current === id) setConfigMessage('Could not check TON availability. Retry by reopening checkout.');
      });
    if (isPending(checkoutMachine.state)) void checkoutMachine.check();
    return () => { generation.current++; };
  }, [plan?.id]);

  if (!plan) return null;
  const shownAttempt = attempt && (busy || attempt.plan === plan.id) ? attempt : null;
  const shownPlan = busy ? PLANS.find((p) => p.id === attempt!.plan) || plan : plan;
  const upgrade = shownAttempt?.ticket?.kind ? shownAttempt.ticket : null;
  const upgradePrice = upgrade ? (shownAttempt!.rail === 'ton' ? `${Number(upgrade.amount) / 1e9} TON` : fmtStars(upgrade.expected_units!)) : '';
  const close = () => {
    generation.current++;
    checkoutMachine.dismiss();
    onClose();
  };
  const pay = async () => {
    if (checkoutMachine.state?.phase === 'review') { await checkoutMachine.confirmUpgrade(); return; }
    if (isPending(checkoutMachine.state)) return;
    setLocalError('');
    if (rail === 'ton') {
      if (!tonEnabled) return;
      if (!isWalletConnected.value) {
        try { await connectWallet(); } catch { setLocalError('Could not open wallet connection. Try again.'); }
        return;
      }
    }
    await checkoutMachine.start(plan.id, rail);
  };

  if (shownAttempt?.phase === 'scheduled') return (
    <Sheet open onClose={close} title="Downgrade scheduled">
      <p role="status">{shownAttempt.message}</p>
      <button class="btn-primary w-full mt-4" onClick={close}>Done</button>
    </Sheet>
  );
  if (shownAttempt?.phase === 'paid') return (
    <Sheet open onClose={close} title="Activation confirmed">
      <div class="text-center py-7">
        <Icon name="check" size={40} class="text-positive mx-auto" />
        <h3 class="text-xl font-bold mt-3">{user.status.value?.plan || shownPlan.name} is active</h3>
        <p class="text-hint text-sm mt-2">Your payment and entitlement were confirmed by the Engine.</p>
        <button class="btn-primary w-full mt-4" onClick={close}>Done</button>
      </div>
    </Sheet>
  );

  return (
    <Sheet open onClose={close} title={busy ? `Checkout: ${shownPlan.name}` : `Upgrade to ${plan.name}`}>
      <fieldset disabled={busy} class="flex gap-2 mb-4" aria-label="Payment method">
        <button class="btn-ghost flex-1" aria-pressed={rail === 'stars'} onClick={() => setRail('stars')}>Stars</button>
        <button class="btn-ghost flex-1" disabled={!tonEnabled} aria-pressed={rail === 'ton'} onClick={() => setRail('ton')}>TON Pay</button>
      </fieldset>
      <p class="text-hint text-xs mb-3">{configMessage}</p>
      <div class="card-raised p-4 mb-3 flex justify-between">
        <span>{shownPlan.name} · {upgrade?.kind === 'downgrade' ? 'Prepaid downgrade · 30 days' : upgrade ? 'Prorated upgrade' : '30 days'}</span>
        <strong>{upgrade ? upgradePrice : (busy ? attempt!.rail : rail) === 'ton'
          ? `${shownPlan.priceTon} TON` : fmtStars(shownPlan.priceStars)}</strong>
      </div>
      {shownAttempt && (
        <div role="status" class="card-raised p-4 mb-3">
          <p class="font-semibold">{shownAttempt.phase === 'review' ? 'Review tier-change quote' : shownAttempt.phase === 'held' ? 'Payment held for review' : busy ? 'Awaiting confirmation' : 'Checkout not completed'}</p>
          <p class="text-hint text-sm mt-2">{shownAttempt.message}</p>
          {shownAttempt.ticket?.reference && <p class="text-xs break-all mt-2">Reference: {shownAttempt.ticket.reference}</p>}
          {shownAttempt.transactionHash && <p class="text-xs break-all mt-2">Transaction: {shownAttempt.transactionHash}</p>}
          {(shownAttempt.phase === 'pending' || shownAttempt.phase === 'held') && (
            <div class="flex gap-2 mt-3">
              <button class="btn-ghost flex-1" onClick={() => void checkoutMachine.check()}>Check status</button>
              {shownAttempt.phase === 'pending' && shownAttempt.rail === 'stars' && !shownAttempt.invoicePaid && (
                <button class="btn-ghost flex-1" onClick={() => checkoutMachine.reopenInvoice()}>Reopen same invoice</button>
              )}
            </div>
          )}
          {busy && shownAttempt.phase !== 'review' && <p class="text-hint text-xs mt-3">You can close this sheet and return to check status. If unresolved, contact @TonGPT_Support with this reference; do not pay again.</p>}
        </div>
      )}
      {localError && <p role="alert" class="text-negative text-sm mb-3">{localError}</p>}
      <button class="btn-primary w-full" onClick={pay} disabled={(busy && shownAttempt?.phase !== 'review') || (rail === 'ton' && !tonEnabled)}>
        {shownAttempt?.phase === 'review' ? `Confirm ${upgrade?.kind}: ${upgradePrice}` : busy ? 'Confirmation pending…' : rail === 'ton' && !isWalletConnected.value ? 'Connect wallet to pay'
          : rail === 'ton' ? `Pay ${plan.priceTon} TON` : `Pay ${fmtStars(plan.priceStars)}`}
      </button>
    </Sheet>
  );
}
