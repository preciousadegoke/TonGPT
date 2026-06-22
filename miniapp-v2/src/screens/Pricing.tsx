import { useEffect, useState } from 'preact/hooks';
import { ScreenHeader } from '@/components/layout/ScreenHeader';
import { CheckoutSheet } from '@/components/CheckoutSheet';
import { AnimatedNumber } from '@/components/ui/AnimatedNumber';
import { PLANS, PLAN_COMPARISON, type Plan } from '@/config';
import { LAUNCH_OFFER, VALUE_PROP, TRUST_BADGES, PRICING_FAQ } from '@/config/marketing';
import { useCountdown } from '@/hooks/useCountdown';
import { getSocialStats, type SocialStats } from '@/lib/social';
import { currentPlan, isPremium } from '@/store';
import { haptic } from '@/lib/telegram';
import { fmtNum, fmtStars } from '@/lib/format';

export default function Pricing() {
  const [selected, setSelected] = useState<Plan | null>(null);
  const [stats, setStats] = useState<SocialStats | null>(null);
  const cd = useCountdown(LAUNCH_OFFER.endsAt);

  useEffect(() => {
    getSocialStats().then(setStats);
  }, []);

  const open = (p: Plan) => {
    haptic.impact('medium');
    setSelected(p);
  };

  const showOffer = LAUNCH_OFFER.active && !(LAUNCH_OFFER.endsAt && cd.done);

  return (
    <div class="screen space-y-6">
      <ScreenHeader title="Upgrade" subtitle="Unlock the full TON intelligence stack" />

      {/* Value hero */}
      <section class="text-center space-y-1.5 pt-1">
        <h2 class="text-xl font-bold leading-snug">
          Trade with an edge the market doesn't see.
        </h2>
        <p class="text-hint text-sm">
          Whale moves, influencer signals and AI analysis — before the candle prints.
        </p>
      </section>

      {/* Honest launch-pricing banner (no fake timer unless a real endsAt is set) */}
      {showOffer && (
        <div class="card p-3 flex items-center justify-between border-accent/40 bg-accent/10">
          <div class="flex items-center gap-2">
            <span class="text-lg">🚀</span>
            <span class="text-sm font-semibold">{LAUNCH_OFFER.label}</span>
          </div>
          {LAUNCH_OFFER.endsAt && !cd.done ? (
            <span class="text-sm font-bold tabular-nums text-accent">
              {cd.d > 0 ? `${cd.d}d ` : ''}{pad(cd.h)}:{pad(cd.m)}:{pad(cd.s)}
            </span>
          ) : (
            <span class="text-xs text-hint">Early access rates</span>
          )}
        </div>
      )}

      {isPremium.value && (
        <div class="card p-3 text-sm text-center border-positive/40">
          You're on <strong>{currentPlan.value}</strong> 👑 — thank you. Manage it in Profile.
        </div>
      )}

      {/* Tier cards */}
      <div class="space-y-3.5">
        {PLANS.map((p, i) => (
          <button
            key={p.id}
            onClick={() => open(p)}
            style={{ animationDelay: `${i * 60}ms` }}
            class={`card w-full text-left p-5 relative overflow-hidden animate-scale-in transition-transform active:scale-[0.99] ${
              p.highlight ? 'border-accent ring-1 ring-accent/50 animate-glow-pulse sheen' : ''
            }`}
          >
            {p.badge && (
              <span
                class="absolute top-0 right-0 text-[10px] font-bold uppercase tracking-wide px-3 py-1 rounded-bl-xl"
                style={{ background: p.highlight ? 'var(--accent)' : 'var(--gold)', color: '#000' }}
              >
                {p.badge}
              </span>
            )}

            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="text-lg font-bold">{p.name}</p>
                <p class="text-hint text-sm">{p.tagline}</p>
              </div>
              <div class="text-right shrink-0">
                <p class="text-2xl font-bold leading-none">
                  {p.priceTon} <span class="text-sm font-medium">TON</span>
                </p>
                <p class="text-hint text-xs mt-1">or {fmtStars(p.priceStars)}</p>
                <p class="text-hint text-[11px]">per month</p>
              </div>
            </div>

            {/* Per-tier value prop — the persuasive one-liner */}
            <p class="mt-3 text-sm text-accent/90 font-medium">{VALUE_PROP[p.id]}</p>

            <ul class="mt-3 space-y-1.5">
              {p.features.map((f) => (
                <li key={f} class="flex items-start gap-2 text-sm">
                  <span class="text-positive mt-0.5">✓</span>
                  <span class="text-hint">{f}</span>
                </li>
              ))}
            </ul>

            <div class={`mt-4 btn ${p.highlight ? 'btn-primary' : 'btn-ghost'} w-full pointer-events-none`}>
              Choose {p.name}
            </div>
          </button>
        ))}
      </div>

      {/* Honest social proof — only renders numbers the backend actually returns */}
      <SocialProof stats={stats} />

      {/* Comparison table */}
      <section>
        <h2 class="text-sm font-semibold text-hint mb-2">Compare every plan</h2>
        <div class="card overflow-x-auto no-scrollbar">
          <table class="w-full text-sm border-collapse">
            <thead>
              <tr class="border-b border-border">
                <th class="text-left p-3 font-medium text-hint sticky left-0 bg-surface z-10">Feature</th>
                {PLANS.map((p) => (
                  <th
                    key={p.id}
                    class={`p-2 font-semibold text-center text-xs whitespace-nowrap ${
                      p.highlight ? 'text-accent' : ''
                    }`}
                  >
                    {p.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {PLAN_COMPARISON.map((row) => (
                <tr key={row.label} class="border-b border-border last:border-0">
                  <td class="p-3 text-hint sticky left-0 bg-surface z-10 whitespace-nowrap">{row.label}</td>
                  {row.values.map((v, i) => (
                    <td
                      key={i}
                      class={`p-2 text-center ${PLANS[i].highlight ? 'bg-accent/5' : ''}`}
                    >
                      {v === true ? (
                        <span class="text-positive">✓</span>
                      ) : v === false ? (
                        <span class="text-hint/40">—</span>
                      ) : (
                        <span class="text-xs font-medium">{v}</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <td class="p-3 sticky left-0 bg-surface z-10" />
                {PLANS.map((p) => (
                  <td key={p.id} class={`p-2 text-center ${p.highlight ? 'bg-accent/5' : ''}`}>
                    <span class="text-xs font-bold">{p.priceTon} TON</span>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Trust badges */}
      <div class="grid grid-cols-3 gap-2">
        {TRUST_BADGES.map((b) => (
          <div key={b.label} class="card p-3 text-center">
            <div class="text-xl">{b.icon}</div>
            <p class="text-[11px] text-hint mt-1 leading-tight">{b.label}</p>
          </div>
        ))}
      </div>

      {/* FAQ — lowers purchase anxiety */}
      <section>
        <h2 class="text-sm font-semibold text-hint mb-2">Common questions</h2>
        <div class="space-y-2">
          {PRICING_FAQ.map((f) => <FaqItem key={f.q} q={f.q} a={f.a} />)}
        </div>
      </section>

      <p class="text-hint text-xs text-center px-4">
        Payments are non-refundable. Memecoins are volatile — nothing here is financial advice.
      </p>

      <CheckoutSheet plan={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

function pad(n: number) {
  return String(n).padStart(2, '0');
}

function SocialProof({ stats }: { stats: SocialStats | null }) {
  const hasNumbers = stats && (stats.members || stats.signals_24h || stats.upgrades_7d);
  if (!hasNumbers) {
    // No fabricated counts — honest, generic trust line.
    return (
      <div class="card p-4 text-center text-sm text-hint">
        Built for serious TON traders. Cancel anytime — nothing auto-renews.
      </div>
    );
  }
  return (
    <div class="card p-4 grid grid-cols-3 divide-x divide-border text-center">
      {stats!.members ? (
        <Stat value={stats!.members} label="members" />
      ) : <span />}
      {stats!.signals_24h ? (
        <Stat value={stats!.signals_24h} label="signals / 24h" />
      ) : <span />}
      {stats!.upgrades_7d ? (
        <Stat value={stats!.upgrades_7d} label="upgrades / 7d" />
      ) : <span />}
    </div>
  );
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div class="px-1">
      <AnimatedNumber value={value} format={(n) => fmtNum(Math.round(n))} class="text-lg font-bold text-accent" />
      <p class="text-hint text-[10px] uppercase tracking-wide mt-0.5">{label}</p>
    </div>
  );
}

function FaqItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div class="card overflow-hidden">
      <button
        class="w-full flex items-center justify-between p-4 text-left"
        aria-expanded={open}
        onClick={() => {
          haptic.select();
          setOpen((v) => !v);
        }}
      >
        <span class="text-sm font-semibold">{q}</span>
        <span class={`text-hint transition-transform ${open ? 'rotate-180' : ''}`}>⌄</span>
      </button>
      {open && <p class="px-4 pb-4 -mt-1 text-sm text-hint animate-fade-in">{a}</p>}
    </div>
  );
}
