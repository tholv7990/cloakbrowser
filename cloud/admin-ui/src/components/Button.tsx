import { forwardRef } from 'react';
import type { ButtonHTMLAttributes } from 'react';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', className, children, ...props },
  ref,
) {
  const baseStyles = 'inline-flex items-center justify-center px-3 py-2 text-sm font-medium rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed';
  const buttonStyle = { minHeight: '2.75rem' };

  const variants = {
    primary: 'bg-accent text-accent-fg hover:bg-accent-hover',
    secondary: 'bg-surface-raised text-ink border border-line-strong hover:bg-surface-sunken',
    ghost: 'text-ink-muted hover:bg-surface-sunken hover:text-ink',
    danger: 'bg-danger/15 text-danger border border-danger/30 hover:bg-danger/25',
  };

  return (
    <button
      ref={ref}
      style={buttonStyle}
      className={`${baseStyles} ${variants[variant]} ${className || ''}`}
      {...props}
    >
      {children}
    </button>
  );
});
