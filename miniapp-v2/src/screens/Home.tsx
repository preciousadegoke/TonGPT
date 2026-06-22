import { useLocation } from 'preact-iso';
import { useEffect, useState } from 'preact/hooks';
import { ScreenHeader } from '@/components/layout/ScreenHeader';
import { WalletButton } from '@/components/WalletButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { user, currentPlan, isPremium, wallet } from '@/store';
import { api } from '@/lib/api';
import { endpoints } from '@/config';
import { tgUser, haptic } from '@/lib/telegram';
import { fmtNum } from '@/lib/format';

interface ScanItem { name: string; symbol: string; change: string; }

export default function Home() {
  const { route } = useLocation();
  const [trending, setTrending] = useState<ScanItem[] | null>(null);

  useEffect(() => {
    api.get<ScanItem[] | { memecoins: ScanItem[] }>(endpoints.memecoins)
      .then((d) => setTrending(Array.isArray(d) ? d.slice(0, 4) : (d.memecoins ?? []).slice(0, 4)))
      .catch(() => setTrending([]));
  }, []);

  const go = (to: string) => { haptic.impact('light'); route(to); };
  const name = tgUser?.first_name ?? 'trader';

  return (
    <div class="screen space-y-5">
      <ScreenHeader title={`gm, ${name}`} subtitle="Your TON intelligence desk" right={<WalletButton />} />

      {/* Plan / status hero card */}
      <section
        class="card p-5 relative overflow-hidden"
        style={{ background: 'linear-gradient(135deg, color-mix(in srgb, var(--accent) 22%, var(--surface)), var(--surface))' }}
      >
        <div class="flex items-center justify-between">
          <div>
            <p class="text-hint text-xs uppercase tracking-wider">Current plan</p>
            {user.loading.value ? (
              <Skeleton w="6rem" h="1.8rem" />
            ) : (
              <p class="text-2xl font-bold flex items-center gap-2">
                {currentPlan.value}
                {isPremium.value && <span class="text-gold">👑</span>}
              </p>
            )}
            {user.status.value?.expiry && (
              <p class="text-hint text-xs mt-1">Renews {new Date(user.status.value.expiry).toLocaleDateString()}</p>
            )}
          </div>
          {!isPremium.value && (
            <button class="btn-primary px-4 py-2 text-sm" onClick={() => go('/pricing')}>
              Upgrade
            </button>
          )}
        </div>
      </section>

      {/* Quick actions */}
      <section>
        <h2 class="text-sm font-semibold text-hint mb-2">Quick actions</h2>
        <div class="grid grid-cols-2 gap-3">
          <QuickAction icon="🧠" label="Ask AI" onClick={() => go('/ai')} />
          <QuickAction icon="🔍" label="Scan token" onClick={() => go('/ai')} />
          <QuickAction icon="🐋" label="Whale alerts" onClick={() => go('/activity')} />
          <QuickAction icon="👛" label="Wallet" onClick={() => go('/wallet')} />
        </div>
      </section>

      {/* Wallet nudge */}
      {!wallet.value.address && (
        <div class="card p-4 flex items-center justify-between">
          <div>
            <p class="font-semibold">Connect your wallet</p>
            <p class="text-hint text-sm">Pay with TON & unlock on-chain features.</p>
          </div>
          <WalletButton />
        </div>
      )}

      {/* Trending preview */}
      <section>
        <div class="flex items-center justify-between mb-2">
          <h2 class="text-sm font-semibold text-hint">Trending now</h2>
          <button class="text-accent text-xs font-semibold" onClick={() => go('/activity')}>See all</button>
        </div>
        <div class="card divide-y divide-border">
          {trending === null
            ? [0, 1, 2].map((i) => (
                <div key={i} class="p-4"><Skeleton w="60%" /></div>
              ))
            : trending.length === 0
              ? <div class="p-4 text-hint text-sm">No data right now.</div>
              : trending.map((t) => (
                  <div key={t.symbol} class="flex items-center justify-between p-4">
                    <div class="flex items-center gap-3">
                      <div class="w-9 h-9 rounded-full bg-surface-2 grid place-items-center text-sm font-bold">
                        {t.symbol?.slice(0, 2)}
                      </div>
                      <div>
                        <p class="font-semibold text-sm">{t.name}</p>
                        <p class="text-hint text-xs">{t.symbol}</p>
                      </div>
                    </div>
                    <span class={`text-sm font-semibold ${String(t.change).startsWith('-') ? 'text-negative' : 'text-positive'}`}>
                      {t.change}
                    </span>
                  </div>
                ))}
        </div>
      </section>

      <StatStrip />
    </div>
  );
}

function QuickAction({ icon, label, onClick }: { icon: string; label: string; onClick: () => void }) {
  return (
    <button class="card p-4 flex items-center gap-3 active:scale-[0.98] transition-transform" onClick={onClick}>
      <span class="text-2xl">{icon}</span>
      <span class="font-semibold text-sm">{label}</span>
    </button>
  );
}

function StatStrip() {
  const stats = [
    { v: '24/7', l: 'Monitoring' },
    { v: `${fmtNum(10400)}+`, l: 'Wallets' },
    { v: '<1s', l: 'Latency' },
  ];
  return (
    <div class="grid grid-cols-3 gap-3">
      {stats.map((s) => (
        <div key={s.l} class="card p-3 text-center">
          <p class="text-lg font-bold text-accent">{s.v}</p>
          <p class="text-hint text-[10px] uppercase tracking-wide">{s.l}</p>
        </div>
      ))}
    </div>
  );
}
