import { useEffect, useState } from 'preact/hooks';

export interface Countdown {
  done: boolean;
  d: number;
  h: number;
  m: number;
  s: number;
}

/**
 * Honest countdown to a real ISO deadline. Returns `done: true` once passed so
 * the UI can hide the offer entirely — never loops or fakes a fresh timer.
 * Pass `undefined` to disable (returns done=true immediately).
 */
export function useCountdown(endsAt?: string): Countdown {
  const target = endsAt ? new Date(endsAt).getTime() : 0;
  const calc = (): Countdown => {
    if (!target) return { done: true, d: 0, h: 0, m: 0, s: 0 };
    const diff = target - Date.now();
    if (diff <= 0) return { done: true, d: 0, h: 0, m: 0, s: 0 };
    return {
      done: false,
      d: Math.floor(diff / 86400000),
      h: Math.floor((diff / 3600000) % 24),
      m: Math.floor((diff / 60000) % 60),
      s: Math.floor((diff / 1000) % 60),
    };
  };

  const [c, setC] = useState<Countdown>(calc);
  useEffect(() => {
    if (!target) return;
    const id = setInterval(() => setC(calc()), 1000);
    return () => clearInterval(id);
  }, [endsAt]);

  return c;
}
