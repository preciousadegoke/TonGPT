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
      <div
        class="absolute inset-0 bg-black/55"
        style={{ backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}
        onClick={onClose}
      />
      <div
        class="relative w-full rounded-t-3xl border-t border-x border-border bg-surface-raised p-5 animate-slide-up shadow-float"
        style={{ paddingBottom: 'calc(20px + var(--tg-bottom))' }}
      >
        <div class="mx-auto mb-4 h-1.5 w-11 rounded-full" style={{ background: 'var(--border-strong)' }} />
        {title && <h3 class="text-lg font-bold mb-4 tracking-tight">{title}</h3>}
        {children}
      </div>
    </div>
  );
}
