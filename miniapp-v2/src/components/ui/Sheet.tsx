import { type ComponentChildren } from 'preact';
import { useEffect } from 'preact/hooks';
import { haptic } from '@/lib/telegram';

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ComponentChildren;
}

/** Accessible bottom sheet with backdrop, focus trap-lite, and Esc to close. */
export function Sheet({ open, onClose, title, children }: SheetProps) {
  useEffect(() => {
    if (!open) return;
    haptic.impact('soft');
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [open]);

  if (!open) return null;

  return (
    <div class="fixed inset-0 z-40 flex items-end animate-fade-in" role="dialog" aria-modal="true" aria-label={title}>
      <div class="absolute inset-0 bg-black/60" onClick={onClose} />
      <div
        class="relative w-full card rounded-b-none rounded-t-3xl p-5 animate-slide-up"
        style={{ paddingBottom: 'calc(20px + var(--tg-bottom))' }}
      >
        <div class="mx-auto mb-4 h-1 w-10 rounded-full bg-border" />
        {title && <h3 class="text-lg font-bold mb-4">{title}</h3>}
        {children}
      </div>
    </div>
  );
}
