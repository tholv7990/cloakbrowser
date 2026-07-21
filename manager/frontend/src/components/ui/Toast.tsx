import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { CheckCircle2, Info, TriangleAlert, X, XCircle } from 'lucide-react';
import { Portal } from './Portal';
import { cn } from '@/lib/cn';

type ToastTone = 'success' | 'danger' | 'info' | 'warning';

interface ToastItem {
  id: number;
  title: string;
  description?: string;
  tone: ToastTone;
}

interface ToastApi {
  toast: (options: { title: string; description?: string; tone?: ToastTone }) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const ICONS: Record<ToastTone, typeof Info> = {
  success: CheckCircle2,
  danger: XCircle,
  info: Info,
  warning: TriangleAlert,
};

const TONE_CLASS: Record<ToastTone, string> = {
  success: 'text-success',
  danger: 'text-danger',
  info: 'text-info',
  warning: 'text-warning',
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counter = useRef(0);

  const dismiss = useCallback((id: number) => {
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const toast = useCallback<ToastApi['toast']>(
    ({ title, description, tone = 'info' }) => {
      counter.current += 1;
      const id = counter.current;
      setItems((current) => [...current, { id, title, description, tone }]);
      window.setTimeout(() => dismiss(id), 5000);
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <Portal>
        <div
          className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2"
          role="region"
          aria-label="Notifications"
        >
          {items.map((item) => {
            const Icon = ICONS[item.tone];
            return (
              <div
                key={item.id}
                role="status"
                className="pointer-events-auto flex items-start gap-3 rounded-lg border border-line-strong bg-surface-raised p-3 shadow-pop animate-scale-in"
              >
                <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', TONE_CLASS[item.tone])} />
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-medium text-ink">{item.title}</p>
                  {item.description && (
                    <p className="mt-0.5 text-2xs text-ink-muted">{item.description}</p>
                  )}
                </div>
                <button
                  type="button"
                  aria-label="Dismiss"
                  onClick={() => dismiss(item.id)}
                  className="text-ink-faint hover:text-ink"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            );
          })}
        </div>
      </Portal>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast must be used within ToastProvider');
  return context;
}
