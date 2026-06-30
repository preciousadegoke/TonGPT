import { haptic } from '@/lib/telegram';

import { type ComponentChildren } from 'preact';

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  icon?: ComponentChildren;
}

interface Props<T extends string> {
  options: SegmentOption<T>[];
  value: T;
  onChange: (v: T) => void;
  'aria-label'?: string;
  class?: string;
}

/**
 * iOS-style segmented control with a sliding thumb that springs between options.
 * The active option sits above a single animated thumb (transform-only, so it's
 * GPU-cheap). Fully keyboard + AT accessible via role="tab".
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  class: cls = '',
  ...rest
}: Props<T>) {
  const n = options.length;
  const index = Math.max(0, options.findIndex((o) => o.value === value));

  return (
    <div
      class={`segmented ${cls}`}
      role="tablist"
      aria-label={rest['aria-label']}
      style={{ gridTemplateColumns: `repeat(${n}, 1fr)` }}
    >
      <span
        class="segmented-thumb"
        aria-hidden="true"
        style={{
          // Thumb spans exactly one segment of the padded track and slides by
          // multiples of its own width — robust for any option count.
          width: `calc((100% - 8px) / ${n})`,
          left: '4px',
          transform: `translateX(calc(${index} * 100%))`,
        }}
      />
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            role="tab"
            aria-selected={active}
            class={`relative z-10 flex items-center justify-center gap-1.5 py-2.5 rounded-xl text-sm font-semibold
              transition-colors duration-200 ${active ? 'text-text' : 'text-hint'}`}
            onClick={() => {
              if (active) return;
              haptic.select();
              onChange(o.value);
            }}
          >
            {o.icon}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
