import { cn } from '@/lib/cn';

/**
 * Original CloakBrowser mark: a shielded aperture — a rounded shield (the
 * managed profile) with an offset inner "cloak" fold that hides its center.
 * No third-party assets.
 */
export function LogoMark({ size = 26, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      className={cn('shrink-0', className)}
    >
      <path
        d="M16 2.5 27 6.2v8.3c0 7.2-4.6 12.9-11 15.5-6.4-2.6-11-8.3-11-15.5V6.2L16 2.5Z"
        className="fill-accent/15 stroke-accent"
        strokeWidth="1.6"
      />
      <path
        d="M16 9.2c3.4 0 6.2 2.9 6.2 6.4 0 1.4-.4 2.6-1.1 3.7-1.2-2.6-3-4-5.1-4-2.6 0-4.2 1.9-4.2 4.4 0 .5.1 1 .2 1.4A6.4 6.4 0 0 1 9.8 15.6c0-3.5 2.8-6.4 6.2-6.4Z"
        className="fill-accent"
      />
    </svg>
  );
}

export function Wordmark({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark />
      {!collapsed && (
        <div className="leading-none">
          <span className="font-display text-[15px] font-semibold tracking-tight text-ink">
            Plasma
          </span>
          <span className="block text-[10px] font-medium uppercase tracking-[0.16em] text-ink-faint">
            Profile Manager
          </span>
        </div>
      )}
    </div>
  );
}
