# TonGPT Mini-App — Design System (v2.1 "Premium")

The 2026 visual refresh. Direction: **Linear's restraint + Stripe's clarity +
Apple's drama**. Extremely clean, generous whitespace, precise hierarchy, and
micro-interactions that feel buttery on a phone. Everything below is already
wired into the codebase — this doc explains *how it hangs together* so future
changes stay consistent.

---

## 1. Token architecture (`src/styles/theme.css`)

The whole palette is driven by CSS custom properties. Only **five base tokens**
are ever overridden at runtime by Telegram (`useTheme()` →
`--bg / --surface / --text / --hint / --accent`). Everything else is **derived
from those five with `color-mix()`**, so the entire UI re-themes instantly and
correctly for *any* Telegram palette (dark, light, or a custom client theme) with
zero hard-coded greys downstream.

| Group | Tokens | Notes |
| --- | --- | --- |
| Brand | `--accent`, `--accent-2`, `--gold`, `--positive`, `--negative` | `--accent-grad` = 135° accent → accent-2 |
| Surfaces | `--surface-raised`, `--surface-sunken` | derived via `color-mix` for layered depth |
| Lines | `--border`, `--border-strong`, `--hairline` | three weights for hierarchy |
| Accent family | `--accent-soft/-softer/-ring/-grad/-grad-soft` | tints + rings + gradients |
| Elevation | `--shadow-sm/-md/-lg/-accent` | soft, low-spread (Linear-style) |
| Chrome | `--glass` | translucent bg for sticky bars |
| Motion | `--ease-spring`, `--ease-out` | one shared spring vocabulary |

**Rule:** never introduce a new literal hex in a component. Add a token (or use
`color-mix(... var(--accent) ...)`) so it survives re-theming.

## 2. Typography

- **Inter** (variable, optical sizing) loaded in `index.html` with
  `preconnect` + `display=swap` → never blocks first paint; the premium system
  stack (`-apple-system`, `SF Pro`, `Segoe UI`) shows instantly as fallback.
- OpenType features on globally (`cv02/cv03/cv04/cv11/ss01`, ligatures) for a
  refined, editorial feel.
- Display type (`h1–h3`) uses tight tracking (`-0.02em`); numbers use
  `tabular-nums` everywhere they animate or align (prices, balances, stats).

## 3. Component primitives (`src/styles/globals.css`)

| Class | Use |
| --- | --- |
| `.card` / `.card-raised` | flat vs. elevated (top-light gradient + soft shadow) |
| `.btn-primary` | gradient fill + accent shadow, springs on press |
| `.btn-outline` / `.btn-ghost` | secondary actions |
| `.segmented` + `.segmented-thumb` | iOS-style control with a sliding thumb |
| `.chip` / `.chip-accent` | pills / badges |
| `.pressable` | unified tactile press (`active:scale-[0.98]`, spring) |
| `.glass` | blurred translucent chrome (tab bar) |
| `.aura` / `.sheen` / `.text-gradient-accent` | hero glow, card sheen, gradient text |
| `[data-reveal]` | scroll-into-view fade/rise (driven by `<Reveal>`) |

## 4. New reusable components

- **`ui/Icon.tsx`** — dependency-free inline-SVG set (Lucide-style, 1.6px
  stroke). Crisp at any size, inherits `currentColor`. Used for structural UI
  (checks, shields, chevrons, rails, nav) where vectors beat emoji. Brand emoji
  stay where they add personality (🐋, 🚀, ⭐).
- **`ui/Reveal.tsx`** — `IntersectionObserver` reveal with optional stagger
  `delay`. GPU-only (opacity + transform). Respects `prefers-reduced-motion`
  (reveals instantly).
- **`ui/Segmented.tsx`** — accessible (`role="tab"`) segmented control with a
  spring-animated thumb. Powers the checkout payment rails and the Activity
  filter.

## 5. Motion & accessibility

- One spring (`cubic-bezier(0.22,1,0.36,1)`) used across presses, sheets, the
  segmented thumb, and reveals — consistent physical feel.
- **`prefers-reduced-motion`** fully honored: all animations collapse to ~0ms
  and `<Reveal>` / `<AnimatedNumber>` snap to final state.
- Focus-visible rings on every interactive element; `aria-selected`,
  `aria-expanded`, `aria-busy`, `aria-modal` set where relevant.
- Haptics on every meaningful tap (select / impact / notify).
- Safe-area insets (`--tg-bottom`) respected by `.screen`, tab bar, sheet, and
  chat composer.

## 6. Screen highlights

- **Pricing (conversion centerpiece):** aspirational gradient hero with accent
  aura; tier cards with a dominant "Most popular" treatment (accent border,
  gradient tint, glow, sheen, ribbon); crisp check rows; per-tier value prop;
  comparison table with highlighted Pro column; honest social proof (never
  fabricated); smooth accordion FAQ; dual TON/Stars framing.
- **Checkout:** segmented rail toggle, clear order summary, lock-iconed CTA,
  celebratory success state (pop + ping + crown), and **error states that always
  offer a real recovery** (retry or switch to Stars).
- **Home / Wallet:** elevated hero cards with ambient accent glow; icon-led
  quick actions; ton_proof status explained in plain language.

## 7. Guardrails (kept from v2)

Honesty is part of the premium feel: no fake countdowns, no invented "N people
bought this" tickers. Social proof only renders numbers the backend actually
returns; the launch banner shows a timer **only** if a real `endsAt` is set.
