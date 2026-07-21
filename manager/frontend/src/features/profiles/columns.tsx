import type { ColumnDef } from '@tanstack/react-table';
import { Pin } from 'lucide-react';
import type { ProfileView } from '@/types/api';
import { FingerprintGlyph } from '@/components/FingerprintGlyph';
import { Checkbox } from '@/components/ui/Checkbox';
import { IconButton } from '@/components/ui/IconButton';
import { Badge, TagChip } from '@/components/ui/Badge';
import { ProxyHealthDot, ReputationBadge, RuntimeBadge } from '@/components/domain/StatusBadges';
import { relativeTime, shortId } from '@/lib/format';
import { cn } from '@/lib/cn';
import { StartStopButton } from './StartStopButton';
import { ProfileRowActions, type RowDialog } from './ProfileRowActions';
import { proxyHealth } from './view';

export interface ColumnMeta {
  id: string;
  label: string;
  canHide: boolean;
  headClassName?: string;
  cellClassName?: string;
}

export const COLUMN_META: ColumnMeta[] = [
  { id: 'select', label: 'Selection', canHide: false, headClassName: 'w-9', cellClassName: 'w-9' },
  { id: 'pinned', label: 'Pin', canHide: false, headClassName: 'w-8', cellClassName: 'w-8' },
  { id: 'name', label: 'Name', canHide: false, headClassName: 'min-w-[220px]' },
  { id: 'browser', label: 'Browser', canHide: true, headClassName: 'w-[150px]' },
  { id: 'proxy', label: 'Proxy', canHide: true, headClassName: 'min-w-[210px]' },
  { id: 'tags', label: 'Tags', canHide: true, headClassName: 'w-[150px]' },
  { id: 'notes', label: 'Notes', canHide: true, headClassName: 'min-w-[150px]' },
  { id: 'reputation', label: 'Reputation', canHide: true, headClassName: 'w-[110px]' },
  { id: 'last_opened', label: 'Last opened', canHide: true, headClassName: 'w-[130px]' },
  { id: 'status', label: 'Status', canHide: true, headClassName: 'w-[130px]' },
  { id: 'message', label: 'Message', canHide: true, headClassName: 'min-w-[150px]' },
  { id: 'runtime', label: 'Start / Stop', canHide: false, headClassName: 'w-[92px]' },
  { id: 'actions', label: 'Actions', canHide: false, headClassName: 'w-12' },
];

export const SORTABLE: Record<string, string> = {
  name: 'name',
  last_opened: 'last_opened_at',
};

export function buildColumns(
  onDialog: (dialog: RowDialog, profile: ProfileView) => void,
  onTogglePin: (profile: ProfileView) => void,
  profileRoot: string,
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
      header: () => 'Name',
      cell: ({ row }) => {
        const profile = row.original;
        return (
          <div className="flex items-center gap-2.5">
            <FingerprintGlyph seed={profile.fingerprint_seed} />
            <div className="min-w-0">
              <div className="truncate text-[13px] font-medium text-ink">{profile.name}</div>
              <div className="data truncate text-[11px] text-ink-faint">{shortId(profile.id)}</div>
            </div>
          </div>
        );
      },
    },
    {
      id: 'browser',
      header: () => 'Browser',
      cell: ({ row }) => (
        <div className="flex flex-col gap-0.5">
          <Badge tone="neutral">Windows</Badge>
          <span className="data text-[11px] text-ink-faint">
            {row.original.browser_version_mode === 'pinned' && row.original.browser_version
              ? `pinned ${row.original.browser_version}`
              : 'installed'}
          </span>
        </div>
      ),
    },
    {
      id: 'proxy',
      header: () => 'Proxy',
      cell: ({ row }) => {
        const proxy = row.original.proxy;
        if (!proxy) return <span className="text-ink-faint">Direct / none</span>;
        return (
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-[13px] text-ink">
                {proxy.country ?? proxy.scheme.toUpperCase()}
              </span>
              <ProxyHealthDot health={proxyHealth(proxy)} />
            </div>
            <div className="data truncate text-[11px] text-ink-faint" title={proxy.masked_endpoint}>
              {proxy.masked_endpoint}
            </div>
          </div>
        );
      },
    },
    {
      id: 'tags',
      header: () => 'Tags',
      cell: ({ row }) => {
        const tags = row.original.tags;
        if (tags.length === 0) return <span className="text-ink-faint">—</span>;
        return (
          <div className="flex flex-wrap gap-1">
            {tags.slice(0, 3).map((tag) => (
              <TagChip key={tag.id} name={tag.name} color={tag.color} />
            ))}
            {tags.length > 3 && <span className="text-2xs text-ink-faint">+{tags.length - 3}</span>}
          </div>
        );
      },
    },
    {
      id: 'notes',
      header: () => 'Notes',
      cell: ({ row }) => {
        const notes = row.original.notes;
        return notes ? (
          <span className="line-clamp-2 text-[12px] text-ink-muted" title={notes}>
            {notes}
          </span>
        ) : (
          <span className="text-ink-faint">—</span>
        );
      },
    },
    {
      id: 'reputation',
      header: () => 'Reputation',
      cell: ({ row }) => <ReputationBadge reputation={row.original.proxy?.reputation ?? null} />,
    },
    {
      id: 'last_opened',
      header: () => 'Last opened',
      cell: ({ row }) => (
        <span className="text-[12px] text-ink-muted">
          {relativeTime(row.original.last_opened_at)}
        </span>
      ),
    },
    {
      id: 'status',
      header: () => 'Status',
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
          <span className="text-ink-faint">No status</span>
        );
      },
    },
    {
      id: 'message',
      header: () => 'Message',
      cell: ({ row }) => {
        const isError = row.original.runtime_state === 'crashed';
        const message = row.original.runtime_message ?? (isError ? 'Crashed' : '—');
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
