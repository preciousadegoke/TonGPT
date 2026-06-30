import { useEffect, useState } from 'preact/hooks';
import { ScreenHeader } from '@/components/layout/ScreenHeader';
import { CheckoutSheet } from '@/components/CheckoutSheet';
import { AnimatedNumber } from '@/components/ui/AnimatedNumber';
import { Reveal } from '@/components/ui/Reveal';
import { Icon } from '@/components/ui/Icon';
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
    <div class="screen space-y-7">
      <ScreenHeader title="Upgrade" subtitle="Unlock the full TON intelligence stack" />

      {/* ── Aspirational hero ─────────────────────────────────────────────── */}
      <section class="relative text-center pt-1 pb-1 aura">
        <div class="relative z-10 space-y-2">
          <span class="chip chip-accent mx-auto">
            <Icon name="sparkles" size={13} /> AI-native trading edge
          </span>
          <h2 class="text-[26px] leading-[1.12] font-extrabold tracking-tight px-2">
            Trade with an edge the
            <br />
            <span class="text-gradient-accent">market doesn&apos;t see.</span>
          </h2>
          <p class="text-hint text-sm max-w-[19rem] mx-auto leading-relaxed">
            Whale moves, influencer signals and AI analysis — before the candle prints.
          </p>
        </div>
      </section>

      {/* Honest launch-pricing banner (no fake timer unless a real endsAt is set) */}
      {showOffer && (
        <div
          class="rounded-2xl p-3.5 flex items-center justify-between border"
          style={{ borderColor: 'var(--accent-ring)', background: 'var(--accent-soft)' }}
        >
          <div class="flex items-center gap-2.5">
            <span class="grid place-items-center w-8 h-8 rounded-xl bg-accent/15 text-accent">
              <Icon name="bolt" size={16} />
            </span>
            <div class="leading-tight">
              <p class="text-sm font-semibold">{LAUNCH_OFFER.label}</p>
              <p class="text-[11px] text-hint">Early-access rates while we launch</p>
            </div>
          </div>
          {LAUNCH_OFFER.endsAt && !cd.done && (
            <span class="text-sm font-bold tabular-nums text-accent">
              {cd.d > 0 ? `${cd.d}d ` : ''}{pad(cd.h)}:{pad(cd.m)}:{pad(cd.s)}
            </span>
          )}
        </div>
      )}

      {isPremium.value && (
        <div
          class="rounded-2xl p-3.5 text-sm text-center border flex items-center justify-center gap-2"
          style={{
            borderColor: 'color-mix(in srgb, var(--positive) 40%, transparent)',
            background: 'color-mix(in srgb, var(--positive) 10%, transparent)',
          }}
        >
          <Icon name="crown" size={16} class="text-gold" />
          You&apos;re on <strong>{currentPlan.value}</strong> — thank you. Manage it in Profile.
        </div>
      )}

      {/* ── Tier cards ────────────────────────────────────────────────────── */}
      <div class="space-y-4">
        {PLANS.map((p, i) => (
          <Reveal key={p.id} delay={i * 70}>
            <TierCard plan={p} onChoose={() => open(p)} />
          </Reveal>
        ))}
      </div>

      {/* Honest social proof — only renders numbers the backend actually returns */}
      <Reveal><SocialProof stats={stats} /></Reveal>

      {/* ── Comparison table ──────────────────────────────────────────────── */}
      <Reveal as="section">
        <h2 class="text-sm font-semibold text-hint mb-2.5 px-1">Compare every plan</h2>
        <div class="card-raised overflow-x-auto no-scrollbar">
          <table class="w-full text-sm border-collapse">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--hairline)' }}>
                <th class="text-left p-3 font-medium text-hint sticky left-0 bg-surface z-10">Feature</th>
                {PLANS.map((p) => (
                  <th
                    key={p.id}
                    class={`p-2 font-bold text-center text-xs whitespace-nowrap ${p.highlight ? 'text-accent' : ''}`}
                  >
                    {p.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {PLAN_COMPARISON.map((row) => (
                <tr key={row.label} style={{ borderBottom: '1px solid var(--hairline)' }}>
                  <td class="p-3 text-hint sticky left-0 bg-surface z-10 whitespace-nowrap">{row.label}</td>
                  {row.values.map((v, i) => (
                    <td key={i} class={`p-2 text-center ${PLANS[i].highlight ? 'bg-accent/5' : ''}`}>
                      {v === true ? (
                        <span class="inline-grid place-items-center text-positive"><Icon name="check" size={15} /></span>
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
      </Reveal>

      {/* ── Trust badges ──────────────────────────────────────────────────── */}
      <Reveal class="grid grid-cols-3 gap-2.5">
        {TRUST_BADGES.map((b) => (
          <div key={b.label} class="card-raised p-3.5 text-center">
            <div class="text-xl">{b.icon}</div>
            <p class="text-[11px] text-hint mt-1.5 leading-tight">{b.label}</p>
          </div>
        ))}
      </Reveal>

      {/* ── FAQ ───────────────────────────────────────────────────────────── */}
      <Reveal as="section">
        <h2 class="text-sm font-semibold text-hint mb-2.5 px-1">Common questions</h2>
        <div class="space-y-2.5">
          {PRICING_FAQ.map((f) => <FaqItem key={f.q} q={f.q} a={f.a} />)}
        </div>
      </Reveal>

      <p class="text-hint text-xs text-center px-6 leading-relaxed">
        Payments are non-refundable. Memecoins are volatile — nothing here is financial advice.
      </p>

      <CheckoutSheet plan={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

/* ── Tier card ─────────────────────────────────────────────────────────── */
function TierCard({ plan: p, onChoose }: { plan: Plan; onChoose: () => void }) {
  return (
    <div
      class={`relative rounded-3xl border p-5 overflow-hidden transition-transform duration-300 ${
        p.highlight ? 'shadow-accent sheen' : 'card-raised'
      }`}
      style={
        p.highlight
          ? {
              borderColor: 'var(--accent)',
              background:
                'linear-gradient(180deg, color-mix(in srgb, var(--accent) 14%, var(--surface)), var(--surface) 55%)',
            }
          : undefined
      }
    >
      {p.badge && (
        <span
          class="absolute top-0 right-0 inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider px-3 py-1.5 rounded-bl-2xl"
          style={{
            background: p.highlight ? 'var(--accent-grad)' : 'var(--gold)',
            color: p.highlight ? 'var(--accent-fg)' : '#1a1300',
          }}
        >
          {p.highlight && <Icon name="star" size={11} />}
          {p.badge}
        </span>
      )}

      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <p class="text-lg font-bold tracking-tight">{p.name}</p>
          <p class="text-hint text-sm">{p.tagline}</p>
        </div>
        <div class="text-right shrink-0">
          <p class="text-[28px] font-extrabold leading-none tracking-tight tabular-nums">
            {p.priceTon} <span class="text-sm font-semibold text-hint">TON</span>
          </p>
          <p class="text-hint text-xs mt-1.5">
            or <span class="font-semibold text-text/90">{fmtStars(p.priceStars)}</span>
          </p>
          <p class="text-hint text-[11px]">per month</p>
        </div>
      </div>

      {/* Per-tier value prop — the persuasive one-liner */}
      <p class={`mt-3.5 text-sm font-medium ${p.highlight ? 'text-accent' : 'text-text/80'}`}>
        {VALUE_PROP[p.id]}
      </p>

      <div class="my-4 h-px" style={{ background: 'var(--hairline)' }} />

      <ul class="space-y-2">
        {p.features.map((f) => (
          <li key={f} class="flex items-start gap-2.5 text-sm">
            <span
              class="mt-0.5 grid place-items-center w-[18px] h-[18px] rounded-full shrink-0"
              style={{
                background: p.highlight
                  ? 'var(--accent-soft)'
                  : 'color-mix(in srgb, var(--positive) 16%, transparent)',
              }}
            >
              <Icon name="check" size={12} class={p.highlight ? 'text-accent' : 'text-positive'} />
            </span>
            <span class="text-text/90">{f}</span>
          </li>
        ))}
      </ul>

      <button onClick={onChoose} class={`mt-5 w-full ${p.highlight ? 'btn-primary' : 'btn-outline'}`}>
        Choose {p.name}
        <Icon name="arrow-right" size={16} />
      </button>
    </div>
  );
}

function pad(n: number) {
  return String(n).padStart(2, '0');
}

function SocialProof({ stats }: { stats: SocialStats | null }) {
  const hasNumbers = stats && (stats.members || stats.signals_24h || stats.upgrades_7d);
  if (!hasNumbers) {
    return (
      <div class="card-raised p-4 text-center text-sm text-hint flex items-center justify-center gap-2">
        <Icon name="shield" size={16} class="text-positive" />
        Built for serious TON traders. Cancel anytime — nothing auto-renews.
      </div>
    );
  }
  return (
    <div class="card-raised p-4 grid grid-cols-3 divide-x divide-border text-center">
      {stats!.members ? <Stat value={stats!.members} label="members" /> : <span />}
      {stats!.signals_24h ? <Stat value={stats!.signals_24h} label="signals / 24h" /> : <span />}
      {stats!.upgrades_7d ? <Stat value={stats!.upgrades_7d} label="upgrades / 7d" /> : <span />}
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
    <div class="card-raised overflow-hidden">
      <button
        class="w-full flex items-center justify-between gap-3 p-4 text-left"
        aria-expanded={open}
        onClick={() => {
          haptic.select();
          setOpen((v) => !v);
        }}
      >
        <span class="text-sm font-semibold">{q}</span>
        <span class={`text-hint transition-transform duration-300 shrink-0 ${open ? 'rotate-180' : ''}`}>
          <Icon name="chevron-down" size={18} />
        </span>
      </button>
      <div class="grid transition-all duration-300 ease-out" style={{ gridTemplateRows: open ? '1fr' : '0fr' }}>
        <div class="overflow-hidden">
          <p class="px-4 pb-4 text-sm text-hint leading-relaxed">{a}</p>
        </div>
      </div>
    </div>
  );
}
