import { type ComponentChildren } from 'preact';

interface Props {
  title: string;
  subtitle?: string;
  /** Small uppercase label above the title (e.g. section/eyebrow). */
  eyebrow?: string;
  right?: ComponentChildren;
}

export function ScreenHeader({ title, subtitle, eyebrow, right }: Props) {
  return (
    <header class="flex items-start justify-between gap-3 pt-2 pb-4">
      <div class="min-w-0">
        {eyebrow && (
          <p class="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent mb-1">{eyebrow}</p>
        )}
        <h1 class="text-[28px] font-extrabold leading-[1.1] tracking-tight truncate">{title}</h1>
        {subtitle && <p class="text-hint text-sm mt-1">{subtitle}</p>}
      </div>
      {right && <div class="shrink-0 pt-1">{right}</div>}
    </header>
  );
}
