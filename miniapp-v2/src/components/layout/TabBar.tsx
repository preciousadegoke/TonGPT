import { useLocation } from 'preact-iso';
import { haptic } from '@/lib/telegram';
import { Icon } from '@/components/ui/Icon';

const TABS = [
  { path: '/', label: 'Home', icon: 'home' as const },
  { path: '/ai', label: 'Ask AI', icon: 'sparkles' as const },
  { path: '/pricing', label: 'Upgrade', icon: 'crown' as const },
  { path: '/activity', label: 'Activity', icon: 'activity' as const },
  { path: '/settings', label: 'Profile', icon: 'user' as const },
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
      class="glass px-2 pt-1.5"
      style={{ paddingBottom: 'calc(8px + var(--tg-bottom))', borderTop: '1px solid var(--border)' }}
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
              class="relative flex flex-col items-center gap-1 py-1.5 px-3 rounded-2xl pressable"
              onClick={() => go(t.path)}
            >
              <span
                class="relative grid place-items-center w-10 h-7 rounded-xl transition-colors duration-300"
                style={active ? { background: 'var(--accent-soft)' } : undefined}
              >
                <span
                  class={`transition-all duration-300 ${active ? 'text-accent scale-110' : 'text-hint scale-100'}`}
                >
                  <Icon name={t.icon} size={20} />
                </span>
              </span>
              <span
                class={`text-[10px] font-semibold transition-colors duration-200 ${active ? 'text-accent' : 'text-hint'}`}
              >
                {t.label}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
