import { type ComponentChildren, type JSX } from 'preact';
import { useEffect, useRef } from 'preact/hooks';

interface Props {
  children: ComponentChildren;
  /** Stagger delay in ms — lets a list cascade in. */
  delay?: number;
  class?: string;
  /** Render as something other than a div (e.g. 'section', 'li'). */
  as?: keyof JSX.IntrinsicElements;
}

/**
 * Scroll-into-view reveal. Adds [data-revealed] when the element enters the
 * viewport (see [data-reveal] styles in globals.css). Respects reduced-motion
 * by revealing immediately. One shared IntersectionObserver pattern, GPU-only
 * (opacity + transform) so it stays buttery on mobile.
 */
export function Reveal({ children, delay = 0, class: cls = '', as = 'div' }: Props) {
  const ref = useRef<HTMLElement>(null);
  const Tag = as as any;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce) {
      el.setAttribute('data-revealed', '');
      return;
    }

    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            setTimeout(() => el.setAttribute('data-revealed', ''), delay);
            io.unobserve(el);
          }
        }
      },
      { threshold: 0.12, rootMargin: '0px 0px -8% 0px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [delay]);

  return (
    <Tag ref={ref} data-reveal class={cls}>
      {children}
    </Tag>
  );
}
