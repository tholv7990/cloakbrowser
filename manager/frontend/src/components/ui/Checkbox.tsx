import { forwardRef } from 'react';
import type { InputHTMLAttributes } from 'react';
import { Check, Minus } from 'lucide-react';
import { cn } from '@/lib/cn';

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  indeterminate?: boolean;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { indeterminate, className, checked, ...props },
  ref,
) {
  return (
    <span className={cn('relative inline-flex h-4 w-4 items-center justify-center', className)}>
      <input
        ref={ref}
        type="checkbox"
        checked={checked}
        className="peer absolute inset-0 h-4 w-4 cursor-pointer appearance-none rounded border border-line-strong bg-surface-sunken checked:border-accent checked:bg-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        {...props}
      />
      {indeterminate ? (
        <Minus
          className="pointer-events-none relative h-3 w-3 text-accent-fg opacity-0 peer-checked:opacity-100"
          strokeWidth={3}
        />
      ) : (
        <Check
          className="pointer-events-none relative h-3 w-3 text-accent-fg opacity-0 peer-checked:opacity-100"
          strokeWidth={3}
        />
      )}
      {indeterminate && (
        <Minus className="pointer-events-none absolute h-3 w-3 text-ink" strokeWidth={3} />
      )}
    </span>
  );
});
