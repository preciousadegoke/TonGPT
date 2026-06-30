import { Icon } from '@/components/ui/Icon';

/** First-paint splash while consent + user status resolve. */
export function BootSplash() {
  return (
    <div class="relative flex flex-col items-center justify-center h-full gap-6 animate-fade-in overflow-hidden">
      {/* Ambient accent aura */}
      <div
        class="absolute w-[320px] h-[320px] rounded-full blur-3xl opacity-60 animate-float"
        style={{ background: 'radial-gradient(circle, var(--accent-soft), transparent 70%)' }}
      />
      <div class="relative">
        <div
          class="w-[72px] h-[72px] rounded-3xl grid place-items-center text-accent-fg shadow-accent"
          style={{ background: 'var(--accent-grad)' }}
        >
          <Icon name="diamond" size={34} />
        </div>
        <div class="absolute inset-0 rounded-3xl ring-2 ring-accent/40 animate-ping" />
      </div>
      <div class="relative text-center">
        <p class="text-lg font-bold tracking-tight">TonGPT</p>
        <p class="text-hint text-[11px] tracking-[0.18em] uppercase mt-1">Loading intelligence…</p>
      </div>
    </div>
  );
}
