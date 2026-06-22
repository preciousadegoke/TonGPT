export const shortAddr = (a?: string | null, s = 4, e = 4) =>
  !a ? '' : a.length <= s + e ? a : `${a.slice(0, s)}…${a.slice(-e)}`;

export const fmtNum = (n: number) =>
  n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : `${n}`;

export const fmtTon = (n: number) => `${n} TON`;
export const fmtStars = (n: number) => `${n.toLocaleString()} ⭐`;

export function timeAgo(d: Date | string | number) {
  const date = new Date(d);
  const s = Math.floor((Date.now() - date.getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export const isValidTonAddress = (a: string) =>
  /^(EQ|UQ)[A-Za-z0-9_-]{46}$/.test(a) || /^[0-9a-fA-F]{64}$/.test(a);
