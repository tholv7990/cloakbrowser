import { NavLink } from 'react-router-dom';
import {
  Activity,
  FolderClosed,
  Gauge,
  Clapperboard,
  LayoutGrid,
  PanelLeftClose,
  PanelLeftOpen,
  Puzzle,
  ShoppingBag,
  Users,
  Workflow,
} from 'lucide-react';
import { Settings as SettingsIcon } from 'lucide-react';
import { Wordmark } from '@/components/Logo';
import { IconButton } from '@/components/ui/IconButton';
import { useUiStore } from '@/app/uiStore';
import { useCapabilities } from '@/hooks/useAppData';
import type { AppCapabilities } from '@/types/api';
import { useT, type TranslationKey } from '@/i18n';
import { cn } from '@/lib/cn';

const NAV: { to: string; key: TranslationKey; icon: typeof Users; cap?: keyof AppCapabilities }[] =
  [
    { to: '/profiles', key: 'nav.profiles', icon: Users },
    { to: '/synchronize', key: 'nav.synchronize', icon: LayoutGrid },
    { to: '/folders', key: 'nav.folders', icon: FolderClosed, cap: 'catalogs' },
    { to: '/extensions', key: 'nav.extensions', icon: Puzzle, cap: 'profiles' },
    { to: '/automation', key: 'nav.automation', icon: Workflow, cap: 'automation' },
    { to: '/shopify', key: 'nav.shopify', icon: ShoppingBag, cap: 'shopify_builder' },
    { to: '/media', key: 'nav.media', icon: Clapperboard, cap: 'media' },
    { to: '/diagnostics', key: 'nav.diagnostics', icon: Activity, cap: 'fingerprint_diagnostics' },
    { to: '/resources', key: 'nav.resources', icon: Gauge, cap: 'resources' },
    { to: '/settings', key: 'nav.settings', icon: SettingsIcon, cap: 'settings' },
  ];

export function Sidebar() {
  const collapsed = useUiStore((state) => state.sidebarCollapsed);
  const toggle = useUiStore((state) => state.toggleSidebar);
  const capabilities = useCapabilities();
  const items = NAV.filter((item) => !item.cap || capabilities[item.cap]);
  const t = useT();

  return (
    <aside
      className={cn(
        'flex h-full shrink-0 flex-col border-r border-line bg-surface transition-[width] duration-200',
        collapsed ? 'w-16' : 'w-60',
      )}
    >
      <div
        className={cn(
          'flex h-14 items-center border-b border-line',
          collapsed ? 'justify-center px-2' : 'px-4',
        )}
      >
        <Wordmark collapsed={collapsed} />
      </div>

      <nav className="flex-1 space-y-1 p-2" aria-label="Primary">
        {items.map(({ to, key, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            title={collapsed ? t(key) : undefined}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-md px-2.5 py-2 text-[13px] font-medium transition-colors',
                collapsed && 'justify-center px-0',
                isActive
                  ? 'bg-accent/15 text-accent'
                  : 'text-ink-muted hover:bg-surface-sunken hover:text-ink',
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
            {!collapsed && <span>{t(key)}</span>}
          </NavLink>
        ))}
      </nav>

      <div className={cn('border-t border-line p-2', collapsed ? 'flex justify-center' : '')}>
        <IconButton label={collapsed ? t('nav.expand') : t('nav.collapse')} onClick={toggle}>
          {collapsed ? (
            <PanelLeftOpen className="h-4 w-4" />
          ) : (
            <PanelLeftClose className="h-4 w-4" />
          )}
        </IconButton>
      </div>
    </aside>
  );
}
