import type { Config } from 'tailwindcss';

// Colors are driven by CSS variables (see src/styles/theme.css) so the whole
// palette re-themes instantly when Telegram sends new themeParams.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        surface: 'var(--surface)',
        'surface-2': 'var(--surface-2)',
        border: 'var(--border)',
        text: 'var(--text)',
        hint: 'var(--hint)',
        accent: 'var(--accent)',
        'accent-fg': 'var(--accent-fg)',
        positive: 'var(--positive)',
        negative: 'var(--negative)',
        gold: 'var(--gold)',
      },
      borderRadius: {
        xl: '16px',
        '2xl': '20px',
        '3xl': '28px',
      },
      fontFamily: {
        sans: ['var(--font-sans)', 'system-ui', 'sans-serif'],
      },
      keyframes: {
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'slide-up': {
          from: { opacity: '0', transform: 'translateY(12px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'scale-in': {
          from: { opacity: '0', transform: 'scale(0.94)' },
          to: { opacity: '1', transform: 'scale(1)' },
        },
        shimmer: { '100%': { transform: 'translateX(100%)' } },
        // Soft pulsing glow for the "most popular" tier.
        'glow-pulse': {
          '0%, 100%': { boxShadow: '0 0 0 0 color-mix(in srgb, var(--accent) 35%, transparent)' },
          '50%': { boxShadow: '0 0 24px 2px color-mix(in srgb, var(--accent) 28%, transparent)' },
        },
        // Diagonal sheen sweeping across a highlighted card.
        sheen: { '0%': { transform: 'translateX(-120%)' }, '100%': { transform: 'translateX(220%)' } },
        // Success checkmark pop.
        pop: {
          '0%': { transform: 'scale(0)', opacity: '0' },
          '60%': { transform: 'scale(1.15)', opacity: '1' },
          '100%': { transform: 'scale(1)', opacity: '1' },
        },
      },
      animation: {
        'fade-in': 'fade-in 0.25s ease-out',
        'slide-up': 'slide-up 0.3s cubic-bezier(0.22, 1, 0.36, 1)',
        'scale-in': 'scale-in 0.22s cubic-bezier(0.22, 1, 0.36, 1)',
        'glow-pulse': 'glow-pulse 2.8s ease-in-out infinite',
        pop: 'pop 0.4s cubic-bezier(0.22, 1, 0.36, 1)',
      },
    },
  },
  plugins: [],
} satisfies Config;
