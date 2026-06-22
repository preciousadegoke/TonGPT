import { useEffect } from 'preact/hooks';
import { tg } from '@/lib/telegram';
import { ui } from '@/store';

/**
 * Maps Telegram themeParams → our CSS custom properties and keeps them in sync
 * when the user flips their Telegram theme live. Also wires the header/background
 * colours and the bottom safe-area inset.
 *
 * Mount once, high in the tree (App).
 */
export function useTheme() {
  useEffect(() => {
    const root = document.documentElement;

    const apply = () => {
      const scheme = tg?.colorScheme ?? 'dark';
      root.classList.remove('light', 'dark');
      root.classList.add(scheme);

      const p = tg?.themeParams ?? {};
      // Only override when Telegram actually provides a value — otherwise our
      // premium defaults in theme.css stand.
      const set = (name: string, val?: string) => {
        if (val) root.style.setProperty(name, val);
      };
      set('--bg', p.bg_color);
      set('--surface', p.secondary_bg_color);
      set('--surface-2', p.secondary_bg_color);
      set('--text', p.text_color);
      set('--hint', p.hint_color);
      set('--accent', p.button_color);
      set('--accent-fg', p.button_text_color);

      // Make the Telegram header blend with the app.
      tg?.setHeaderColor?.(p.bg_color ?? (scheme === 'dark' ? '#000000' : '#ffffff'));
      tg?.setBackgroundColor?.(p.bg_color ?? (scheme === 'dark' ? '#000000' : '#ffffff'));

      ui.colorScheme.value = scheme;
    };

    const applyInsets = () => {
      // viewportStableHeight shrinks when the keyboard or Telegram chrome shows.
      const stable = tg?.viewportStableHeight;
      if (stable) {
        const bottom = Math.max(0, window.innerHeight - stable);
        root.style.setProperty('--tg-bottom', `${bottom}px`);
      }
    };

    apply();
    applyInsets();

    tg?.onEvent('themeChanged', apply);
    tg?.onEvent('viewportChanged', applyInsets);
    return () => {
      tg?.offEvent('themeChanged', apply);
      tg?.offEvent('viewportChanged', applyInsets);
    };
  }, []);
}
