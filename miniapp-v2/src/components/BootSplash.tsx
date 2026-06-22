/** First-paint splash while consent + user status resolve. */
export function BootSplash() {
  return (
    <div class="flex flex-col items-center justify-center h-full gap-5 animate-fade-in">
      <div class="relative">
        <div class="w-16 h-16 rounded-2xl bg-accent/20 grid place-items-center">
          <span class="text-3xl">💎</span>
        </div>
        <div class="absolute inset-0 rounded-2xl ring-2 ring-accent/40 animate-ping" />
      </div>
      <p class="text-hint text-sm tracking-wide uppercase">Loading TonGPT…</p>
    </div>
  );
}
