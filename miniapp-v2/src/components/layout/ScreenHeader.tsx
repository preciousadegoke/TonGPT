import { type ComponentChildren } from 'preact';

interface Props {
  title: string;
  subtitle?: string;
  right?: ComponentChildren;
}

export function ScreenHeader({ title, subtitle, right }: Props) {
  return (
    <header class="flex items-start justify-between pt-2 pb-4">
      <div>
        <h1 class="text-2xl font-bold leading-tight">{title}</h1>
        {subtitle && <p class="text-hint text-sm mt-0.5">{subtitle}</p>}
      </div>
      {right}
    </header>
  );
}
