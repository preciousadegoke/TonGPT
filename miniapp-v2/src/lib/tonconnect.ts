/**
 * TonConnect 2.0 integration with ton_proof.
 *
 * Flow:
 *   1. Before the connect modal opens, fetch a server nonce
 *      (GET /wallet/generate-payload) and arm it as the ton_proof request.
 *   2. When the wallet connects, it returns a signed proof.
 *   3. We POST the proof + address to /wallet/auth, which the backend verifies
 *      and binds to the Telegram user. Only then is the wallet "authed".
 *
 * This closes the gap in the old app, where "connected" never proved ownership.
 */
import { TonConnectUI } from '@tonconnect/ui';
import type { Wallet } from '@tonconnect/ui';
import { env, endpoints } from '@/config';
import { api } from '@/lib/api';
import { wallet as walletSignal, toast } from '@/store';
import { haptic } from '@/lib/telegram';

let tonConnectUI: TonConnectUI | null = null;

export function getTonConnect(): TonConnectUI {
  if (tonConnectUI) return tonConnectUI;
  tonConnectUI = new TonConnectUI({
    manifestUrl: env.manifestUrl,
    actionsConfiguration: {
      // Return user to the Mini-App after wallet interaction.
      twaReturnUrl: `https://t.me/${env.botUsername}/app` as `${string}://${string}`,
    },
  });
  return tonConnectUI;
}

/** Arm a fresh ton_proof challenge from the backend nonce. */
async function armProof() {
  const ui = getTonConnect();
  ui.setConnectRequestParameters({ state: 'loading' });
  try {
    const { payload } = await api.get<{ payload: string }>(endpoints.walletPayload);
    ui.setConnectRequestParameters({ state: 'ready', value: { tonProof: payload } });
  } catch {
    // If the nonce service is down, allow connect without proof rather than block.
    ui.setConnectRequestParameters(null);
  }
}

async function verifyProof(w: Wallet) {
  const proof = (w.connectItems?.tonProof as { proof?: unknown } | undefined)?.proof;
  if (!proof) {
    toast('Wallet connected, but ownership not verified', 'warning');
    return false;
  }
  try {
    await api.post(endpoints.walletAuth, {
      address: w.account.address,
      network: w.account.chain,
      public_key: w.account.publicKey,
      // REQUIRED: the StateInit is the trust anchor the backend uses to bind the
      // public key to the address (hash(StateInit) == address). Without it the
      // server cannot prove ownership and will reject the link.
      state_init: w.account.walletStateInit,
      proof,
    });
    return true;
  } catch {
    toast('Wallet verification failed', 'error');
    return false;
  }
}

function toFriendly(raw: string) {
  // Address comes raw (0:...); the SDK exposes a friendly form on the account
  // when available. Fall back to the raw string.
  return raw;
}

export function initWalletListener() {
  const ui = getTonConnect();
  ui.onStatusChange(async (w) => {
    if (w) {
      const authed = await verifyProof(w);
      walletSignal.value = {
        address: w.account.address,
        friendlyAddress: toFriendly(w.account.address),
        appName: w.device.appName,
        authed,
      };
      haptic.notify(authed ? 'success' : 'warning');
    } else {
      walletSignal.value = { address: null, friendlyAddress: null, appName: null, authed: false };
    }
  });
}

export async function connectWallet() {
  haptic.impact('light');
  await armProof();
  await getTonConnect().openModal();
}

export async function disconnectWallet() {
  await getTonConnect().disconnect();
}
