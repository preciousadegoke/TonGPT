/**
 * Typed, defensive facade over the Telegram WebApp SDK.
 *
 * Every method no-ops gracefully when running outside Telegram (e.g. `vite dev`
 * in a desktop browser), so the same code path works in dev and in-client.
 */

type ThemeParams = {
  bg_color?: string;
  secondary_bg_color?: string;
  text_color?: string;
  hint_color?: string;
  link_color?: string;
  button_color?: string;
  button_text_color?: string;
  header_bg_color?: string;
};

type TgUser = {
  id: number;
  first_name?: string;
  last_name?: string;
  username?: string;
  language_code?: string;
  photo_url?: string;
};

type HapticStyle = 'light' | 'medium' | 'heavy' | 'rigid' | 'soft';
type NotifType = 'error' | 'success' | 'warning';

interface TelegramWebApp {
  initData: string;
  initDataUnsafe: { user?: TgUser; start_param?: string };
  version: string;
  colorScheme: 'light' | 'dark';
  themeParams: ThemeParams;
  isExpanded: boolean;
  viewportStableHeight: number;
  ready(): void;
  expand(): void;
  close(): void;
  disableVerticalSwipes?(): void;
  setHeaderColor?(color: string): void;
  setBackgroundColor?(color: string): void;
  openTelegramLink(url: string): void;
  openLink(url: string, opts?: { try_instant_view?: boolean }): void;
  openInvoice(url: string, cb?: (status: string) => void): void;
  onEvent(type: string, cb: (...args: unknown[]) => void): void;
  offEvent(type: string, cb: (...args: unknown[]) => void): void;
  HapticFeedback?: {
    impactOccurred(style: HapticStyle): void;
    notificationOccurred(type: NotifType): void;
    selectionChanged(): void;
  };
  MainButton: {
    text: string;
    isVisible: boolean;
    isActive: boolean;
    showProgress(leave?: boolean): void;
    hideProgress(): void;
    setText(t: string): void;
    show(): void;
    hide(): void;
    enable(): void;
    disable(): void;
    setParams(p: Partial<{ text: string; color: string; text_color: string; is_active: boolean; is_visible: boolean }>): void;
    onClick(cb: () => void): void;
    offClick(cb: () => void): void;
  };
  BackButton: {
    isVisible: boolean;
    show(): void;
    hide(): void;
    onClick(cb: () => void): void;
    offClick(cb: () => void): void;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

export const tg: TelegramWebApp | undefined = window.Telegram?.WebApp;
export const isTelegram = Boolean(tg && tg.initData);

/** Raw initData string — sent to the backend for HMAC verification on every request. */
export const initData = tg?.initData ?? '';

export const tgUser = tg?.initDataUnsafe?.user;

/** Deep-link start param (e.g. referral token or `?startapp=pricing`). */
export const startParam = tg?.initDataUnsafe?.start_param;

/** Call once on boot: expand, mark ready, lock vertical swipe-to-close. */
export function bootstrapTelegram() {
  if (!tg) return;
  tg.ready();
  tg.expand();
  tg.disableVerticalSwipes?.();
}

export const haptic = {
  impact(style: HapticStyle = 'light') {
    tg?.HapticFeedback?.impactOccurred(style);
  },
  notify(type: NotifType) {
    tg?.HapticFeedback?.notificationOccurred(type);
  },
  select() {
    tg?.HapticFeedback?.selectionChanged();
  },
};

/** Open a Telegram deep link (tg://… or https://t.me/…) inside the client. */
export function openTelegramLink(url: string) {
  if (tg) tg.openTelegramLink(url);
  else window.open(url, '_blank');
}
