/**
 * Global app state via @preact/signals. Signals give us fine-grained reactivity
 * with zero boilerplate — components read `.value` and re-render only on change.
 * No Redux/Zustand needed at this size.
 */
import { signal, computed } from '@preact/signals';
import type { PlanId } from '@/config';

// ── User / subscription ───────────────────────────────────────────────
export interface UserStatus {
  plan: string; // "Free" | "Starter" | "Pro" | ...
  expiry: string | null;
  is_premium: boolean;
}

export const user = {
  status: signal<UserStatus | null>(null),
  loading: signal(true),
  consentAccepted: signal<boolean | null>(null),
};

export const isPremium = computed(() => user.status.value?.is_premium ?? false);
export const currentPlan = computed(() => user.status.value?.plan ?? 'Free');

// ── Wallet ────────────────────────────────────────────────────────────
export interface WalletState {
  address: string | null;
  friendlyAddress: string | null;
  appName: string | null;
  authed: boolean; // ton_proof verified by backend
}

export const wallet = signal<WalletState>({
  address: null,
  friendlyAddress: null,
  appName: null,
  authed: false,
});

export const isWalletConnected = computed(() => Boolean(wallet.value.address));

// ── UI ────────────────────────────────────────────────────────────────
export interface Toast {
  id: number;
  message: string;
  type: 'success' | 'error' | 'info' | 'warning';
}

export const ui = {
  colorScheme: signal<'light' | 'dark'>('dark'),
  toasts: signal<Toast[]>([]),
  checkoutPlan: signal<PlanId | null>(null), // drives the checkout sheet
};

let toastSeq = 0;
export function toast(message: string, type: Toast['type'] = 'info') {
  const id = ++toastSeq;
  ui.toasts.value = [...ui.toasts.value, { id, message, type }];
  setTimeout(() => {
    ui.toasts.value = ui.toasts.value.filter((t) => t.id !== id);
  }, 3200);
}
