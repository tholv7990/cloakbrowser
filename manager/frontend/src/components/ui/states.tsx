import type { ReactNode } from 'react';
import { TriangleAlert } from 'lucide-react';
import { cn } from '@/lib/cn';
import { Button } from './Button';
import { Spinner } from './Spinner';

export function LoadingBlock({
  label = 'Loading…',
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 py-16 text-ink-muted',
        className,
      )}
      role="status"
      aria-live="polite"
    >
      <Spinner className="h-6 w-6 text-accent" />
      <p className="text-[13px]">{label}</p>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 px-6 py-16 text-center',
        className,
      )}
    >
      {icon && (
        <div className="flex h-12 w-12 items-center justify-center rounded-full border border-line bg-surface-sunken text-ink-faint">
          {icon}
        </div>
      )}
      <div className="max-w-sm">
        <p className="font-display text-base font-semibold text-ink">{title}</p>
        {description && <p className="mt-1 text-[13px] text-ink-muted">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function ErrorState({
  title = 'Something went wrong',
  message,
  onRetry,
  className,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 px-6 py-16 text-center',
        className,
      )}
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-full border border-danger/30 bg-danger/10 text-danger">
        <TriangleAlert className="h-5 w-5" />
      </div>
      <div className="max-w-md">
        <p className="font-display text-base font-semibold text-ink">{title}</p>
        <p className="mt-1 text-[13px] text-ink-muted">{message}</p>
      </div>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded bg-surface-sunken', className)} />;
}
