# TonGPT Mini-App v2 (Preact + Vite + TypeScript)

A premium, native-feeling Telegram Mini-App for the TON ecosystem. Rebuild of the
legacy Vanilla-JS `miniapp/`, designed for fast load, delightful UX, and high
upgrade conversion.

## Stack & why

| Concern | Choice | Why |
| --- | --- | --- |
| UI | **Preact 10** | React DX, ~4 kB runtime → fast first paint inside Telegram |
| Build | **Vite 5** | Instant HMR, native code-splitting, tiny prod bundles |
| Language | **TypeScript (strict)** | Catches payment/wallet bugs before users do |
| State | **@preact/signals** | Fine-grained reactivity, zero boilerplate. No Redux/Zustand needed at this size |
| Routing | **preact-iso** | 1 kB router with `lazy()` + `ErrorBoundary`, per-route code splitting |
| Wallet | **@tonconnect/ui** | TonConnect 2.0 + ton_proof, split into its own chunk |
| Payments | TON Pay + **Telegram Stars** | Dual rail in one `<CheckoutSheet/>` |
| PWA/offline | **vite-plugin-pwa** | App-shell precache + NetworkFirst API cache |

## Project structure

```
miniapp-v2/
├─ index.html               # Telegram SDK + anti-FOUC theme preload
├─ vite.config.ts           # code-split, PWA, /api dev proxy
├─ tailwind.config.ts       # tokens mapped to CSS vars (re-themes live)
├─ tonconnect-manifest.json # MUST be on a public HTTPS URL
├─ .env.example
└─ src/
   ├─ main.tsx              # render root
   ├─ App.tsx               # shell: theme, consent gate, lazy router, tab bar
   ├─ config/index.ts       # env, endpoints, PLANS (parity w/ bot)
   ├─ store/index.ts        # signals: user, wallet, ui, toast()
   ├─ lib/
   │  ├─ telegram.ts        # typed WebApp facade + haptics + deep links
   │  ├─ api.ts             # fetch client, auto-attaches initData header
   │  ├─ tonconnect.ts      # TonConnect 2.0 + ton_proof verification
   │  ├─ payments.ts        # payWithTon() + payWithStars()
   │  ├─ user.ts            # status / consent / referral
   │  └─ format.ts
   ├─ hooks/
   │  ├─ useTheme.ts        # themeParams → CSS vars, live sync, safe areas
   │  ├─ useMainButton.ts   # declarative Telegram MainButton
   │  └─ useBackButton.ts   # declarative Telegram BackButton
   ├─ components/
   │  ├─ ConsentGate.tsx  BootSplash.tsx  WalletButton.tsx  CheckoutSheet.tsx
   │  ├─ layout/  TabBar.tsx  ScreenHeader.tsx
   │  └─ ui/      ErrorBoundary.tsx Skeleton.tsx ScreenFallback.tsx Toast.tsx Sheet.tsx
   └─ screens/
      Home.tsx  Pricing.tsx  Wallet.tsx  AIChat.tsx  Activity.tsx  Settings.tsx
```

## Getting started

```bash
cd miniapp-v2
cp .env.example .env.local      # fill VITE_TONCONNECT_MANIFEST_URL etc.
npm install
npm run dev                     # http://localhost:5173, /api proxied to :8000
npm run build                   # → dist/  (tsc typecheck + vite build)
```

To test inside Telegram, expose dev over HTTPS (e.g. `npm run tunnel` or
cloudflared/ngrok) and set that URL as your bot's Mini-App URL in @BotFather.

## Theme integration (how it works)

`useTheme()` mounts once in `App`. On boot and on every Telegram `themeChanged`
event it copies `themeParams` (bg, text, hint, button colours) into CSS custom
properties (`--bg`, `--text`, `--accent`, …). Tailwind colours are defined as
those vars, so the entire UI re-themes instantly — light or dark — to match the
user's Telegram client. `index.html` paints the bg colour before JS loads to
avoid a flash. Safe-area insets are tracked via `viewportChanged`.

## Plan parity (important)

`src/config/index.ts → PLANS` is aligned **exactly** to the backend's single
source of truth, `core/pricing.py`:

| Plan | TON | Stars |
| --- | --- | --- |
| Starter | 10 | 1,335 ⭐ |
| Pro | 30 | 4,000 ⭐ |
| Pro+ | 60 | 8,000 ⭐ |
| Elite | 120 | 16,000 ⭐ |

If you change `core/pricing.py`, change `config/index.ts` too. (A prior version
of the frontend undercharged TON by ~half — fixed.)

## Launch & conversion

- **Launch steps + final checklist:** see [LAUNCH.md](./LAUNCH.md).
- **Conversion copy** (value props, FAQ, trust badges, honest launch-offer flag)
  lives in `src/config/marketing.ts` — tune without touching logic.
- **Social proof is honest:** `src/lib/social.ts` only renders numbers the
  backend actually returns (`GET /api/stats`); otherwise a generic trust line —
  never fabricated counts. No fake countdowns unless you set a real `endsAt`.
