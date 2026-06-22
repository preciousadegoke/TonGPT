import { useEffect, useRef } from 'preact/hooks';
import { tg } from '@/lib/telegram';

type MainButtonOpts = {
  text: string;
  onClick: () => void;
  visible?: boolean;
  active?: boolean;
  loading?: boolean;
  color?: string;
};

/**
 * Declaratively drive the Telegram MainButton from a component.
 * Hides itself on unmount, so each screen owns its own CTA.
 */
export function useMainButton({
  text,
  onClick,
  visible = true,
  active = true,
  loading = false,
  color,
}: MainButtonOpts) {
  const handler = useRef(onClick);
  handler.current = onClick;

  useEffect(() => {
    const mb = tg?.MainButton;
    if (!mb) return;

    const click = () => handler.current();
    mb.onClick(click);

    return () => {
      mb.offClick(click);
      mb.hide();
      mb.hideProgress();
    };
  }, []);

  useEffect(() => {
    const mb = tg?.MainButton;
    if (!mb) return;
    mb.setParams({ text, is_active: active, ...(color ? { color } : {}) });
    if (visible) mb.show();
    else mb.hide();
    if (loading) mb.showProgress(false);
    else mb.hideProgress();
    if (active) mb.enable();
    else mb.disable();
  }, [text, visible, active, loading, color]);
}
