import { cloneElement, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import { Portal } from './Portal';
import { useOnClickOutside } from '@/hooks/useOnClickOutside';
import { cn } from '@/lib/cn';

/** Trigger + floating panel for arbitrary content that stays open until dismissed. */
export function Popover({
  trigger,
  children,
  align = 'start',
  width = 280,
}: {
  trigger: ReactElement;
  children: ReactNode | ((close: () => void) => ReactNode);
  align?: 'start' | 'end';
  width?: number;
}) {
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useOnClickOutside([triggerRef, panelRef], close, open);

  const reposition = useCallback(() => {
    const el = triggerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const left = align === 'end' ? rect.right - width : rect.left;
    setCoords({
      top: rect.bottom + 6,
      left: Math.max(8, Math.min(left, window.innerWidth - width - 8)),
    });
  }, [align, width]);

  useLayoutEffect(() => {
    if (open) reposition();
  }, [open, reposition]);

  useEffect(() => {
    if (!open) return;
    const handler = () => reposition();
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && close();
    window.addEventListener('resize', handler);
    window.addEventListener('scroll', handler, true);
    document.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('resize', handler);
      window.removeEventListener('scroll', handler, true);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, reposition, close]);

  const triggerNode = cloneElement(trigger as ReactElement<Record<string, unknown>>, {
    ref: triggerRef,
    'aria-haspopup': 'dialog',
    'aria-expanded': open,
    onClick: (event: React.MouseEvent) => {
      (trigger.props as { onClick?: (e: React.MouseEvent) => void }).onClick?.(event);
      setOpen((value) => !value);
    },
  });

  return (
    <>
      {triggerNode}
      {open && coords && (
        <Portal>
          <div
            ref={panelRef}
            role="dialog"
            style={{ position: 'fixed', top: coords.top, left: coords.left, width }}
            className={cn(
              'z-50 max-h-[70vh] overflow-y-auto rounded-lg border border-line-strong bg-surface-raised p-3 shadow-pop animate-scale-in',
            )}
          >
            {typeof children === 'function' ? children(close) : children}
          </div>
        </Portal>
      )}
    </>
  );
}
