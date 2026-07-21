import type { Folder } from '@/types/api';
import { useT } from '@/i18n';
import { cn } from '@/lib/cn';

export type ProfileTab =
  { kind: 'all' } | { kind: 'pinned' } | { kind: 'recent' } | { kind: 'folder'; id: string };

function isActive(active: ProfileTab, tab: ProfileTab): boolean {
  if (active.kind !== tab.kind) return false;
  if (active.kind === 'folder' && tab.kind === 'folder') return active.id === tab.id;
  return true;
}

export function ProfilesTabs({
  active,
  onChange,
  folders,
  total,
}: {
  active: ProfileTab;
  onChange: (tab: ProfileTab) => void;
  folders: Folder[];
  total: number;
}) {
  const t = useT();
  const tabs: { tab: ProfileTab; label: string; count?: number }[] = [
    { tab: { kind: 'all' }, label: t('profiles.tab.all'), count: total },
    { tab: { kind: 'pinned' }, label: t('profiles.tab.pinned') },
    { tab: { kind: 'recent' }, label: t('profiles.tab.recent') },
    ...folders.slice(0, 6).map((folder) => ({
      tab: { kind: 'folder', id: folder.id } as ProfileTab,
      label: folder.name,
      count: folder.profile_count,
    })),
  ];

  return (
    <div
      className="flex items-center gap-1 overflow-x-auto border-b border-line"
      role="tablist"
      aria-label="Profile views"
    >
      {tabs.map(({ tab, label, count }) => {
        const activeTab = isActive(active, tab);
        return (
          <button
            key={label}
            role="tab"
            aria-selected={activeTab}
            onClick={() => onChange(tab)}
            className={cn(
              'flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-[13px] font-medium transition-colors',
              activeTab
                ? 'border-accent text-ink'
                : 'border-transparent text-ink-muted hover:text-ink',
            )}
          >
            {label}
            {count !== undefined && (
              <span
                className={cn(
                  'rounded px-1.5 py-0.5 text-2xs',
                  activeTab ? 'bg-accent/15 text-accent' : 'bg-surface-sunken text-ink-faint',
                )}
              >
                {count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
