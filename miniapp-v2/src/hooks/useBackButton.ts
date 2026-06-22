import { useEffect, useRef } from 'preact/hooks';
import { tg } from '@/lib/telegram';

/**
 * Show the native Telegram BackButton while mounted and route its tap to `onBack`.
 * Pass `show=false` to keep it hidden (e.g. on the root tab screens).
 */
export function useBackButton(onBack: () => void, show = true) {
  const handler = useRef(onBack);
  handler.current = onBack;

  useEffect(() => {
    const bb = tg?.BackButton;
    if (!bb) return;

    const click = () => handler.current();
    bb.onClick(click);
    if (show) bb.show();
    else bb.hide();

    return () => {
      bb.offClick(click);
      bb.hide();
    };
  }, [show]);
}
