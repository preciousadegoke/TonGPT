import { useLocation } from 'preact-iso';
import { haptic } from '@/lib/telegram';

const TABS = [
  { path: '/', label: 'Home', icon: '🏠' },
  { path: '/ai', label: 'Ask AI', icon: '🧠' },
  { path: '/pricing', label: 'Upgrade', icon: '👑' },
  { path: '/activity', label: 'Activity', icon: '📈' },
  { path: '/settings', label: 'Profile', icon: '⚙️' },
];

export function TabBar() {
  const { path, route } = useLocation();

  const go = (to: string) => {
    if (to === path) return;
    haptic.select();
    route(to);
  };

  return (
    <nav
      class="border-t border-border bg-surface/95 backdrop-blur px-1 pt-1"
      style={{ paddingBottom: 'calc(6px + var(--tg-bottom))' }}
      role="tablist"
      aria-label="Primary"
    >
      <div class="flex justify-around items-stretch">
        {TABS.map((t) => {
          const active = t.path === path;
          return (
            <button
              key={t.path}
              role="tab"
              aria-selected={active}
              aria-label={t.label}
              class={`flex flex-col items-center gap-0.5 py-2 px-3 rounded-xl transition-colors ${
                active ? 'text-accent' : 'text-hint'
              }`}
              onClick={() => go(t.path)}
            >
              <span class={`text-lg transition-transform ${active ? 'scale-110' : ''}`}>{t.icon}</span>
              <span class="text-[10px] font-semibold">{t.label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
