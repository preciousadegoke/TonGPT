import { ui } from '@/store';

const ICON: Record<string, string> = {
  success: '✓',
  error: '✕',
  warning: '!',
  info: 'i',
};
const COLOR: Record<string, string> = {
  success: 'var(--positive)',
  error: 'var(--negative)',
  warning: 'var(--gold)',
  info: 'var(--accent)',
};

/** Stacked toast host. Mount once near the root. */
export function ToastHost() {
  return (
    <div
      class="fixed left-0 right-0 z-50 flex flex-col items-center gap-2 px-4 pointer-events-none"
      style={{ bottom: 'calc(96px + var(--tg-bottom))' }}
      aria-live="polite"
    >
      {ui.toasts.value.map((t) => (
        <div
          key={t.id}
          class="card flex items-center gap-3 px-4 py-3 w-full max-w-sm animate-slide-up shadow-lg"
          role="status"
        >
          <span
            class="grid place-items-center w-6 h-6 rounded-full text-xs font-bold text-black shrink-0"
            style={{ background: COLOR[t.type] }}
          >
            {ICON[t.type]}
          </span>
          <span class="text-sm">{t.message}</span>
        </div>
      ))}
    </div>
  );
}
