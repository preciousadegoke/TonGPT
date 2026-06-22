import { wallet, isWalletConnected } from '@/store';
import { connectWallet, disconnectWallet } from '@/lib/tonconnect';
import { shortAddr } from '@/lib/format';

/** Compact connect/disconnect pill used in headers. */
export function WalletButton() {
  const w = wallet.value;
  if (isWalletConnected.value) {
    return (
      <button
        class="btn-ghost px-3 py-2 text-xs"
        onClick={() => disconnectWallet()}
        aria-label="Disconnect wallet"
      >
        <span class={w.authed ? 'text-positive' : 'text-gold'}>●</span>
        {shortAddr(w.friendlyAddress)}
      </button>
    );
  }
  return (
    <button class="btn-primary px-3 py-2 text-xs" onClick={() => connectWallet()}>
      Connect Wallet
    </button>
  );
}
