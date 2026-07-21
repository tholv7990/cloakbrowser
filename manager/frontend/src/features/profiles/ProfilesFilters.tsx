import { Filter } from 'lucide-react';
import type { Folder, Tag, WorkflowStatus } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Popover } from '@/components/ui/Popover';
import { Select } from '@/components/ui/Select';
import { Field } from '@/components/ui/Field';
import { Badge } from '@/components/ui/Badge';
import { activeFilterCount, emptyFilters, type ProfileFilters } from './types';

const PINNED_OPTIONS = [
  { value: '', label: 'Pinned and unpinned' },
  { value: 'true', label: 'Pinned only' },
  { value: 'false', label: 'Unpinned only' },
];

export function ProfilesFilters({
  filters,
  onChange,
  folders,
  tags,
  statuses,
}: {
  filters: ProfileFilters;
  onChange: (filters: ProfileFilters) => void;
  folders: Folder[];
  tags: Tag[];
  statuses: WorkflowStatus[];
}) {
  const count = activeFilterCount(filters);

  return (
    <Popover
      align="start"
      width={280}
      trigger={
        <Button variant="secondary" size="sm">
          <Filter className="h-3.5 w-3.5" />
          Filters
          {count > 0 && <Badge tone="accent">{count}</Badge>}
        </Button>
      }
    >
      {(close) => (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-[13px] font-semibold text-ink">Filter profiles</p>
            <button
              type="button"
              className="text-2xs text-ink-faint hover:text-ink disabled:opacity-40"
              disabled={count === 0}
              onClick={() => onChange(emptyFilters)}
            >
              Reset
            </button>
          </div>

          <Field label="Folder">
            <Select
              value={filters.folder_id ?? ''}
              onChange={(e) => onChange({ ...filters, folder_id: e.target.value || null })}
              options={[
                { value: '', label: 'Any folder' },
                ...folders.map((f) => ({ value: f.id, label: f.name })),
              ]}
            />
          </Field>
          <Field label="Tag">
            <Select
              value={filters.tag_id ?? ''}
              onChange={(e) => onChange({ ...filters, tag_id: e.target.value || null })}
              options={[
                { value: '', label: 'Any tag' },
                ...tags.map((t) => ({ value: t.id, label: t.name })),
              ]}
            />
          </Field>
          <Field label="Workflow status">
            <Select
              value={filters.workflow_status_id ?? ''}
              onChange={(e) => onChange({ ...filters, workflow_status_id: e.target.value || null })}
              options={[
                { value: '', label: 'Any status' },
                ...statuses.map((s) => ({ value: s.id, label: s.name })),
              ]}
            />
          </Field>
          <Field label="Pinned">
            <Select
              value={filters.pinned === null ? '' : String(filters.pinned)}
              onChange={(e) =>
                onChange({
                  ...filters,
                  pinned: e.target.value === '' ? null : e.target.value === 'true',
                })
              }
              options={PINNED_OPTIONS}
            />
          </Field>

          <div className="flex justify-end pt-1">
            <Button size="sm" variant="primary" onClick={close}>
              Done
            </Button>
          </div>
        </div>
      )}
    </Popover>
  );
}
