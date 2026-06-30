/**
 * Lightweight inline-SVG icon set (Lucide-style, 1.6px stroke). Crisp at any
 * size, inherits `currentColor`, zero dependencies. We use these for structural
 * UI (checks, shields, rails, chevrons) where sharp vector lines read more
 * premium than emoji — brand emoji stay where they add personality.
 */
import { type JSX } from 'preact';

type IconName =
  | 'check'
  | 'shield'
  | 'bolt'
  | 'sparkles'
  | 'arrow-up'
  | 'arrow-right'
  | 'chevron-down'
  | 'chevron-right'
  | 'star'
  | 'diamond'
  | 'lock'
  | 'refresh'
  | 'crown'
  | 'wallet'
  | 'copy'
  | 'external'
  | 'home'
  | 'activity'
  | 'user'
  | 'send'
  | 'search'
  | 'whale';

interface Props extends JSX.SVGAttributes<SVGSVGElement> {
  name: IconName;
  size?: number;
}

const PATHS: Record<IconName, JSX.Element> = {
  check: <path d="M20 6 9 17l-5-5" />,
  shield: (
    <>
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  bolt: <path d="M13 2 3 14h7l-1 8 10-12h-7l1-8Z" />,
  sparkles: (
    <>
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4" />
      <path d="m6.5 6.5 1.8 1.8M15.7 15.7l1.8 1.8M17.5 6.5l-1.8 1.8M8.3 15.7l-1.8 1.8" />
    </>
  ),
  'arrow-up': <path d="M12 19V5M5 12l7-7 7 7" />,
  'arrow-right': <path d="M5 12h14M12 5l7 7-7 7" />,
  'chevron-down': <path d="m6 9 6 6 6-6" />,
  'chevron-right': <path d="m9 6 6 6-6 6" />,
  star: <path d="M12 2.5l2.9 6.1 6.6.9-4.8 4.6 1.2 6.6L12 18.6 6.1 21.3l1.2-6.6L2.5 9.5l6.6-.9L12 2.5Z" />,
  diamond: <path d="M12 2 22 9l-10 13L2 9l10-7Zm0 0v20M2 9h20" />,
  lock: (
    <>
      <rect x="4" y="11" width="16" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </>
  ),
  refresh: <path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v5h-5" />,
  crown: <path d="M3 7l4 5 5-7 5 7 4-5-2 13H5L3 7Z" />,
  wallet: (
    <>
      <path d="M3 7a2 2 0 0 1 2-2h13a1 1 0 0 1 1 1v2" />
      <path d="M3 7v10a2 2 0 0 0 2 2h14a1 1 0 0 0 1-1v-3" />
      <path d="M21 11h-5a2 2 0 0 0 0 4h5v-4Z" />
    </>
  ),
  copy: (
    <>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </>
  ),
  external: (
    <>
      <path d="M15 3h6v6" />
      <path d="M10 14 21 3" />
      <path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" />
    </>
  ),
  home: (
    <>
      <path d="M3 10.5 12 3l9 7.5" />
      <path d="M5 9.5V20a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9.5" />
      <path d="M9.5 21v-6h5v6" />
    </>
  ),
  activity: <path d="M3 12h4l2.5-7 5 16 2.5-9H21" />,
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </>
  ),
  send: <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z" />,
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </>
  ),
  whale: (
    <>
      <path d="M3 11c0 4 3 7 7 7h2a6 6 0 0 0 6-6V8" />
      <path d="M18 8c1.5 0 3-1 3-3-2 0-3 1-3 3Z" />
      <path d="M3 11c-1 0-2 .6-2 2M7 13v.01" />
    </>
  ),
};

export function Icon({ name, size = 18, ...rest }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.6"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {PATHS[name]}
    </svg>
  );
}
