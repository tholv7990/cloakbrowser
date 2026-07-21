import {
  cloneElement,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import type { ReactElement, ReactNode } from 'react';
import { Portal } from './Portal';
import { useOnClickOutside } from '@/hooks/useOnClickOutside';
import { cn } from '@/lib/cn';

interface MenuContextValue {
  close: () => void;
}
const MenuContext = createContext<MenuContextValue>({ close: () => {} });

interface Coords {
  top: number;
  left: number;
  minWidth: number;
  placement: 'bottom' | 'top';
}

export function Menu({
  trigger,
  children,
  align = 'end',
  width = 240,
}: {
  trigger: ReactElement;
  children: ReactNode;
  align?: 'start' | 'end';
  width?: number;
}) {
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<Coords | null>(null);
  const triggerRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => setOpen(false), []);
  useOnClickOutside([triggerRef, menuRef], close, open);

  const reposition = useCallback(() => {
    const el = triggerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    const placement: Coords['placement'] =
      spaceBelow < 280 && rect.top > spaceBelow ? 'top' : 'bottom';
    const left = align === 'end' ? rect.right - width : rect.left;
    setCoords({
      top: placement === 'bottom' ? rect.bottom + 6 : rect.top - 6,
      left: Math.max(8, Math.min(left, window.innerWidth - width - 8)),
      minWidth: Math.max(width, rect.width),
      placement,
    });
  }, [align, width]);

  useLayoutEffect(() => {
    if (open) reposition();
  }, [open, reposition]);

  useEffect(() => {
    if (!open) return;
    const handler = () => reposition();
    window.addEventListener('resize', handler);
    window.addEventListener('scroll', handler, true);
    return () => {
      window.removeEventListener('resize', handler);
      window.removeEventListener('scroll', handler, true);
    };
  }, [open, reposition]);

  useEffect(() => {
    if (!open) return;
    const first = menuRef.current?.querySelector<HTMLElement>(
      '[role="menuitem"]:not([aria-disabled="true"])',
    );
    first?.focus();
  }, [open, coords]);

  const onMenuKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
      triggerRef.current?.focus();
      return;
    }
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>(
        '[role="menuitem"]:not([aria-disabled="true"])',
      ) ?? [],
    );
    if (items.length === 0) return;
    const currentIndex = items.indexOf(document.activeElement as HTMLElement);
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      items[(currentIndex + 1) % items.length].focus();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      items[(currentIndex - 1 + items.length) % items.length].focus();
    } else if (event.key === 'Home') {
      event.preventDefault();
      items[0].focus();
    } else if (event.key === 'End') {
      event.preventDefault();
      items[items.length - 1].focus();
    }
  };

  const triggerNode = cloneElement(trigger as ReactElement<Record<string, unknown>>, {
    ref: triggerRef,
    'aria-haspopup': 'menu',
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
            ref={menuRef}
            role="menu"
            onKeyDown={onMenuKeyDown}
            style={{
              position: 'fixed',
              top: coords.placement === 'bottom' ? coords.top : undefined,
              bottom: coords.placement === 'top' ? window.innerHeight - coords.top : undefined,
              left: coords.left,
              minWidth: coords.minWidth,
            }}
            className={cn(
              'z-50 max-h-[70vh] overflow-y-auto rounded-lg border border-line-strong bg-surface-raised p-1 shadow-pop',
              'animate-scale-in',
            )}
          >
            <MenuContext.Provider value={{ close }}>{children}</MenuContext.Provider>
          </div>
        </Portal>
      )}
    </>
  );
}

export function MenuItem({
  children,
  onSelect,
  icon,
  disabled,
  tone = 'default',
  closeOnSelect = true,
}: {
  children: ReactNode;
  onSelect?: () => void;
  icon?: ReactNode;
  disabled?: boolean;
  tone?: 'default' | 'danger';
  closeOnSelect?: boolean;
}) {
  const { close } = useContext(MenuContext);
  return (
    <button
      type="button"
      role="menuitem"
      aria-disabled={disabled || undefined}
      disabled={disabled}
      tabIndex={-1}
      onClick={() => {
        if (disabled) return;
        onSelect?.();
        if (closeOnSelect) close();
      }}
      className={cn(
        'flex w-full items-center gap-2.5 rounded px-2.5 py-1.5 text-left text-[13px] transition-colors',
        'focus:outline-none focus-visible:bg-surface-sunken',
        disabled && 'cursor-not-allowed opacity-40',
        tone === 'danger'
          ? 'text-danger hover:bg-danger/10 focus:bg-danger/10'
          : 'text-ink hover:bg-surface-sunken focus:bg-surface-sunken',
      )}
    >
      {icon && (
        <span className="flex h-4 w-4 shrink-0 items-center justify-center text-ink-faint">
          {icon}
        </span>
      )}
      <span className="min-w-0 flex-1 truncate">{children}</span>
    </button>
  );
}

export function MenuGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="group" aria-label={label} className="py-0.5">
      <p className="px-2.5 pb-1 pt-1.5 text-[10px] font-semibold uppercase tracking-wider text-ink-faint">
        {label}
      </p>
      {children}
    </div>
  );
}

export function MenuSeparator() {
  return <div role="separator" className="my-1 h-px bg-line" />;
}
