import { wallet, isWalletConnected } from '@/store';
import { connectWallet, disconnectWallet } from '@/lib/tonconnect';
import { shortAddr } from '@/lib/format';
import { Icon } from '@/components/ui/Icon';

/** Compact connect/disconnect pill used in headers. */
export function WalletButton() {
  const w = wallet.value;
  if (isWalletConnected.value) {
    return (
      <button
        class="btn-ghost px-3 py-2 text-xs font-mono gap-1.5"
        onClick={() => disconnectWallet()}
        aria-label="Disconnect wallet"
      >
        <span class={w.authed ? 'text-positive' : 'text-gold'}>●</span>
        {shortAddr(w.friendlyAddress)}
      </button>
    );
  }
  return (
    <button class="btn-primary px-3.5 py-2 text-xs" onClick={() => connectWallet()}>
      <Icon name="wallet" size={14} /> Connect
    </button>
  );
}
