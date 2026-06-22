import { useEffect, useRef, useState } from 'preact/hooks';

interface Props {
  value: number;
  duration?: number;
  format?: (n: number) => string;
  class?: string;
}

/**
 * Counts up to `value` once on mount (and on change). Respects reduced-motion by
 * snapping straight to the final value. Used for honest stats (e.g. member count).
 */
export function AnimatedNumber({ value, duration = 900, format = (n) => `${Math.round(n)}`, class: cls }: Props) {
  const [display, setDisplay] = useState(0);
  const raf = useRef(0);

  useEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce) {
      setDisplay(value);
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      // easeOutCubic
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(value * eased);
      if (t < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [value, duration]);

  return <span class={`tabular-nums ${cls ?? ''}`}>{format(display)}</span>;
}
