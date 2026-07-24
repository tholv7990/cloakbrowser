import { forwardRef, useState } from 'react';
import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { cn } from '@/lib/cn';
import { useT } from '@/i18n';

const base =
  'w-full rounded-md border border-line-strong bg-surface-sunken px-3 text-sm text-ink ' +
  'placeholder:text-ink-faint transition-colors focus:border-accent focus:outline-none ' +
  'focus:shadow-focus disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-danger';

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
  mono?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, invalid, mono, type, ...props },
  ref,
) {
  const t = useT();
  const [revealed, setRevealed] = useState(false);

  if (type === 'password') {
    return (
      <div className="relative">
        <input
          ref={ref}
          type={revealed ? 'text' : 'password'}
          aria-invalid={invalid || undefined}
          className={cn(base, 'h-9 pr-9', mono && 'font-mono', className)}
          {...props}
        />
        <button
          type="button"
          onClick={() => setRevealed((value) => !value)}
          className="absolute inset-y-0 right-0 flex items-center px-2.5 text-ink-faint transition-colors hover:text-ink"
        >
          {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          <span className="sr-only">{t(revealed ? 'common.hidePassword' : 'common.showPassword')}</span>
        </button>
      </div>
    );
  }

  return (
    <input
      ref={ref}
      type={type}
      aria-invalid={invalid || undefined}
      className={cn(base, 'h-9', mono && 'font-mono', className)}
      {...props}
    />
  );
});

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { className, invalid, rows = 4, ...props },
  ref,
) {
  return (
    <textarea
      ref={ref}
      rows={rows}
      aria-invalid={invalid || undefined}
      className={cn(base, 'py-2 leading-relaxed', className)}
      {...props}
    />
  );
});
