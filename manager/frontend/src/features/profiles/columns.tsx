import type { ColumnDef } from '@tanstack/react-table';
import { Pin } from 'lucide-react';
import type { ProfileView } from '@/types/api';
import type { TranslationKey } from '@/i18n';
import { Checkbox } from '@/components/ui/Checkbox';
import { IconButton } from '@/components/ui/IconButton';
import { Badge } from '@/components/ui/Badge';
import { ProxyHealthDot, ReputationBadge, RuntimeBadge } from '@/components/domain/StatusBadges';
import { countryFlag, relativeTime } from '@/lib/format';
import { cn } from '@/lib/cn';
import { StartStopButton } from './StartStopButton';
import { ProfileRowActions, type RowDialog } from './ProfileRowActions';
import { EditableNameCell, EditableNotesCell, TagsCell } from './EditableCells';
import { proxyHealth } from './view';

export interface ColumnMeta {
  id: string;
  labelKey: TranslationKey;
  canHide: boolean;
  headClassName?: string;
  cellClassName?: string;
}

export const COLUMN_META: ColumnMeta[] = [
  {
    id: 'select',
    labelKey: 'col.selection',
    canHide: false,
    headClassName: 'w-9',
    cellClassName: 'w-9',
  },
  { id: 'pinned', labelKey: 'col.pin', canHide: false, headClassName: 'w-8', cellClassName: 'w-8' },
  { id: 'name', labelKey: 'col.name', canHide: false, headClassName: 'min-w-[220px]' },
  { id: 'browser', labelKey: 'col.browser', canHide: true, headClassName: 'w-[150px]' },
  { id: 'proxy', labelKey: 'col.proxy', canHide: true, headClassName: 'min-w-[210px]' },
  { id: 'tags', labelKey: 'col.tags', canHide: true, headClassName: 'w-[150px]' },
  { id: 'notes', labelKey: 'col.notes', canHide: true, headClassName: 'min-w-[150px]' },
  { id: 'reputation', labelKey: 'col.reputation', canHide: true, headClassName: 'w-[110px]' },
  { id: 'last_opened', labelKey: 'col.lastOpened', canHide: true, headClassName: 'w-[130px]' },
  { id: 'status', labelKey: 'col.status', canHide: true, headClassName: 'w-[130px]' },
  { id: 'message', labelKey: 'col.message', canHide: true, headClassName: 'min-w-[150px]' },
  { id: 'runtime', labelKey: 'col.startStop', canHide: false, headClassName: 'w-[92px]' },
  { id: 'actions', labelKey: 'col.actions', canHide: false, headClassName: 'w-12' },
];

export const SORTABLE: Record<string, string> = {
  name: 'name',
  last_opened: 'last_opened_at',
};

export function buildColumns(
  onDialog: (dialog: RowDialog, profile: ProfileView) => void,
  onTogglePin: (profile: ProfileView) => void,
  profileRoot: string,
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string,
): ColumnDef<ProfileView>[] {
  return [
    {
      id: 'select',
      header: ({ table }) => (
        <Checkbox
          aria-label="Select all profiles on this page"
          checked={table.getIsAllRowsSelected()}
          indeterminate={table.getIsSomeRowsSelected() && !table.getIsAllRowsSelected()}
          onChange={(event) => table.toggleAllRowsSelected(event.currentTarget.checked)}
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          aria-label={`Select ${row.original.name}`}
          checked={row.getIsSelected()}
          onChange={(event) => row.toggleSelected(event.currentTarget.checked)}
        />
      ),
    },
    {
      id: 'pinned',
      header: () => <span className="sr-only">Pinned</span>,
      cell: ({ row }) => {
        const profile = row.original;
        return (
          <IconButton
            size="sm"
            label={profile.pinned ? `Unpin ${profile.name}` : `Pin ${profile.name}`}
            aria-pressed={profile.pinned}
            onClick={() => onTogglePin(profile)}
          >
            <Pin
              className={cn(
                'h-3.5 w-3.5',
                profile.pinned ? 'fill-accent text-accent' : 'text-ink-faint',
              )}
            />
          </IconButton>
        );
      },
    },
    {
      id: 'name',
      header: () => t('col.name'),
      cell: ({ row }) => <EditableNameCell profile={row.original} />,
    },
    {
      id: 'browser',
      header: () => t('col.browser'),
      cell: ({ row }) => (
        <div className="flex flex-col gap-0.5">
          <Badge tone="neutral">Windows</Badge>
          <span className="data text-[11px] text-ink-faint">
            {row.original.browser_version_mode === 'pinned' && row.original.browser_version
              ? t('col.pinnedVersion', { version: row.original.browser_version })
              : t('col.installed')}
          </span>
        </div>
      ),
    },
    {
      id: 'proxy',
      header: () => t('col.proxy'),
      cell: ({ row }) => {
        const profile = row.original;
        const proxy = profile.proxy;
        return (
          <button
            type="button"
            onClick={() => onDialog('assign-proxy', profile)}
            title={t('col.clickAssignProxy')}
            className="group min-w-0 text-left"
          >
            {proxy ? (
              <>
                <div className="flex items-center gap-2">
                  <span className="text-[13px] text-ink group-hover:text-accent">
                    {proxy.country ? (
                      <>
                        {countryFlag(proxy.country) && (
                          <span className="mr-1" aria-hidden="true">
                            {countryFlag(proxy.country)}
                          </span>
                        )}
                        {proxy.country}
                      </>
                    ) : (
                      proxy.scheme.toUpperCase()
                    )}
                  </span>
                  <ProxyHealthDot health={proxyHealth(proxy)} />
                </div>
                <div
                  className="data truncate text-[11px] text-ink-faint"
                  title={proxy.masked_endpoint}
                >
                  {proxy.masked_endpoint}
                </div>
              </>
            ) : (
              <span className="text-ink-faint group-hover:text-ink">{t('col.assignProxy')}</span>
            )}
          </button>
        );
      },
    },
    {
      id: 'tags',
      header: () => t('col.tags'),
      cell: ({ row }) => <TagsCell profile={row.original} />,
    },
    {
      id: 'notes',
      header: () => t('col.notes'),
      cell: ({ row }) => <EditableNotesCell profile={row.original} />,
    },
    {
      id: 'reputation',
      header: () => t('col.reputation'),
      cell: ({ row }) => <ReputationBadge reputation={row.original.proxy?.reputation ?? null} />,
    },
    {
      id: 'last_opened',
      header: () => t('col.lastOpened'),
      cell: ({ row }) => (
        <span className="text-[12px] text-ink-muted">
          {relativeTime(row.original.last_opened_at)}
        </span>
      ),
    },
    {
      id: 'status',
      header: () => t('col.status'),
      cell: ({ row }) => {
        const status = row.original.workflow_status;
        return status ? (
          <span
            className="inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-2xs font-medium"
            style={{
              color: status.color,
              borderColor: `${status.color}55`,
              backgroundColor: `${status.color}18`,
            }}
          >
            {status.name}
          </span>
        ) : (
          <span className="text-ink-faint">{t('col.noStatus')}</span>
        );
      },
    },
    {
      id: 'message',
      header: () => t('col.message'),
      cell: ({ row }) => {
        const isError = row.original.runtime_state === 'crashed';
        const message = row.original.runtime_message ?? (isError ? t('col.crashed') : '—');
        return (
          <div className="flex flex-col gap-1">
            <RuntimeBadge state={row.original.runtime_state} />
            <span
              className={cn('truncate text-[11px]', isError ? 'text-danger' : 'text-ink-faint')}
              title={message}
            >
              {message}
            </span>
          </div>
        );
      },
    },
    {
      id: 'runtime',
      header: () => <span className="sr-only">Start or stop</span>,
      cell: ({ row }) => <StartStopButton profile={row.original} />,
    },
    {
      id: 'actions',
      header: () => <span className="sr-only">Row actions</span>,
      cell: ({ row }) => (
        <ProfileRowActions profile={row.original} profileRoot={profileRoot} onDialog={onDialog} />
      ),
    },
  ];
}
