import { useLocation } from 'react-router-dom';
import { LogOut, Monitor, Moon, Sun } from 'lucide-react';
import { useAppData } from '@/hooks/useAppData';
import { useRealtime } from '@/realtime/RealtimeProvider';
import { useUiStore, type ThemePreference } from '@/app/uiStore';
import { StatusDot } from '@/components/ui/Badge';
import { IconButton } from '@/components/ui/IconButton';
import { LanguageToggle } from '@/components/LanguageToggle';
import { useT, type TranslationKey } from '@/i18n';
import { useLogout } from '@/features/auth/api';
import { cn } from '@/lib/cn';
import type { ConnectionState } from '@/types/events';

function titleKey(pathname: string): TranslationKey {
  if (pathname.startsWith('/profiles/new')) return 'title.newProfile';
  if (/^\/profiles\/[^/]+\/edit/.test(pathname)) return 'title.editProfile';
  if (pathname.startsWith('/folders')) return 'title.folders';
  if (pathname.startsWith('/proxies')) return 'title.proxies';
  if (pathname.startsWith('/diagnostics')) return 'title.diagnostics';
  if (pathname.startsWith('/resources')) return 'title.resources';
  if (pathname.startsWith('/settings')) return 'title.settings';
  return 'title.profiles';
}

const CONNECTION: Record<
  ConnectionState,
  { key: TranslationKey; tone: 'success' | 'warning' | 'danger' }
> = {
  connected: { key: 'conn.connected', tone: 'success' },
  connecting: { key: 'conn.connecting', tone: 'warning' },
  reconnecting: { key: 'conn.reconnecting', tone: 'warning' },
  disconnected: { key: 'conn.disconnected', tone: 'danger' },
};

const THEMES: { value: ThemePreference; icon: typeof Sun; key: TranslationKey }[] = [
  { value: 'light', icon: Sun, key: 'theme.light' },
  { value: 'dark', icon: Moon, key: 'theme.dark' },
  { value: 'system', icon: Monitor, key: 'theme.system' },
];

function ThemeControl() {
  const t = useT();
  const theme = useUiStore((state) => state.theme);
  const setTheme = useUiStore((state) => state.setTheme);
  return (
    <div
      className="flex items-center gap-0.5 rounded-md border border-line bg-surface-sunken p-0.5"
      role="group"
      aria-label="Theme"
    >
      {THEMES.map(({ value, icon: Icon, key }) => (
        <button
          key={value}
          type="button"
          aria-label={t(key)}
          aria-pressed={theme === value}
          onClick={() => setTheme(value)}
          className={cn(
            'flex h-7 w-7 items-center justify-center rounded transition-colors',
            theme === value
              ? 'bg-surface-raised text-accent shadow-sm'
              : 'text-ink-faint hover:text-ink',
          )}
        >
          <Icon className="h-3.5 w-3.5" />
        </button>
      ))}
    </div>
  );
}

export function Header() {
  const t = useT();
  const location = useLocation();
  const { connectionState } = useRealtime();
  const app = useAppData();
  const logout = useLogout();
  const connection = CONNECTION[connectionState];
  const running = app.runningCount;

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-line bg-surface px-5">
      <h1 className="font-display text-[17px] font-semibold text-ink">
        {t(titleKey(location.pathname))}
      </h1>

      <div className="flex items-center gap-3">
        <span className="hidden items-center gap-1.5 rounded-md border border-line bg-surface-sunken px-2.5 py-1.5 text-2xs text-ink-muted sm:inline-flex">
          <StatusDot tone={running > 0 ? 'success' : 'neutral'} pulse={running > 0} />
          {t('header.running', { count: running })}
        </span>

        <span
          className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface-sunken px-2.5 py-1.5 text-2xs text-ink-muted"
          title={t(connection.key)}
        >
          <StatusDot tone={connection.tone} pulse={connectionState !== 'connected'} />
          {t(connection.key)}
        </span>

        <LanguageToggle />
        <ThemeControl />
        <IconButton label={t('auth.signOut')} onClick={() => logout.mutate()}>
          <LogOut className="h-4 w-4" />
        </IconButton>
      </div>
    </header>
  );
}
