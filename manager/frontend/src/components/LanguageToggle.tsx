import { useUiStore } from '@/app/uiStore';
import { LANGUAGES } from '@/i18n';
import { cn } from '@/lib/cn';

/** English / Vietnamese segmented toggle. */
export function LanguageToggle() {
  const language = useUiStore((state) => state.language);
  const setLanguage = useUiStore((state) => state.setLanguage);
  return (
    <div
      className="flex items-center gap-0.5 rounded-md border border-line bg-surface-sunken p-0.5"
      role="group"
      aria-label="Language"
    >
      {LANGUAGES.map(({ value, label }) => (
        <button
          key={value}
          type="button"
          aria-pressed={language === value}
          onClick={() => setLanguage(value)}
          className={cn(
            'flex h-7 min-w-8 items-center justify-center rounded px-1.5 text-2xs font-semibold transition-colors',
            language === value
              ? 'bg-surface-raised text-accent shadow-sm'
              : 'text-ink-faint hover:text-ink',
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
