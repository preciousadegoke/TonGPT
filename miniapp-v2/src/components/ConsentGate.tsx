import { useState } from 'preact/hooks';
import { recordConsent } from '@/lib/user';
import { tg, haptic } from '@/lib/telegram';
import { toast } from '@/store';

/** Terms-of-service gate. Mirrors the backend consent flow (v1). */
export function ConsentGate() {
  const [busy, setBusy] = useState(false);

  const accept = async () => {
    setBusy(true);
    haptic.impact('medium');
    try {
      await recordConsent();
    } catch {
      toast('Failed to record consent. Try again.', 'error');
      setBusy(false);
    }
  };

  return (
    <div class="screen flex flex-col gap-6 max-w-md mx-auto pt-10">
      <div class="text-center space-y-2">
        <div class="text-6xl">📜</div>
        <h1 class="text-2xl font-bold">Terms of Service</h1>
        <p class="text-hint">Before you begin, please review our terms.</p>
      </div>

      <div class="card p-4 text-sm space-y-3 max-h-64 overflow-y-auto">
        <p>By using TonGPT, you agree that:</p>
        <ul class="list-disc pl-5 space-y-2 text-hint">
          <li>TonGPT provides AI analysis and metrics for informational purposes only.</li>
          <li><strong class="text-text">Not financial advice.</strong> No output constitutes investment or trading advice.</li>
          <li>You are solely responsible for any transactions made with connected wallets.</li>
          <li>Memecoins are highly volatile and carry significant risk of loss.</li>
        </ul>
      </div>

      <div class="space-y-3">
        <button class="btn-primary w-full" onClick={accept} disabled={busy}>
          {busy ? 'Accepting…' : 'I Accept'}
        </button>
        <button
          class="btn-ghost w-full text-negative"
          onClick={() => tg?.close()}
        >
          Decline & Exit
        </button>
      </div>
    </div>
  );
}
