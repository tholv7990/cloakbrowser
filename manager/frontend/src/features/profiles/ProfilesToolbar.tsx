import { Download, Plus, Search, Upload, X } from 'lucide-react';
import type { Folder, Tag, WorkflowStatus } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { IconButton } from '@/components/ui/IconButton';
import { useT } from '@/i18n';
import { ProfilesFilters } from './ProfilesFilters';
import { ColumnSettings } from './ColumnSettings';
import type { ProfileFilters } from './types';

export function ProfilesToolbar({
  search,
  onSearch,
  filters,
  onFilters,
  folders,
  tags,
  statuses,
  onNew,
  onImport,
  onExport,
}: {
  search: string;
  onSearch: (value: string) => void;
  filters: ProfileFilters;
  onFilters: (filters: ProfileFilters) => void;
  folders: Folder[];
  tags: Tag[];
  statuses: WorkflowStatus[];
  onNew: () => void;
  onImport: () => void;
  onExport: () => void;
}) {
  const t = useT();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-[220px] flex-1">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
        <input
          type="search"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder={t('common.searchProfiles')}
          aria-label="Search profiles"
          className="h-9 w-full rounded-md border border-line-strong bg-surface-sunken pl-9 pr-9 text-sm text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none focus:shadow-focus"
        />
        {search && (
          <IconButton
            label="Clear search"
            size="sm"
            className="absolute right-1 top-1/2 -translate-y-1/2"
            onClick={() => onSearch('')}
          >
            <X className="h-3.5 w-3.5" />
          </IconButton>
        )}
      </div>

      <ProfilesFilters
        filters={filters}
        onChange={onFilters}
        folders={folders}
        tags={tags}
        statuses={statuses}
      />

      <div className="ml-auto flex items-center gap-2">
        <ColumnSettings />
        <Button variant="secondary" size="sm" onClick={onImport}>
          <Upload className="h-3.5 w-3.5" /> {t('common.import')}
        </Button>
        <Button variant="secondary" size="sm" onClick={onExport}>
          <Download className="h-3.5 w-3.5" /> {t('common.export')}
        </Button>
        <Button variant="primary" size="sm" onClick={onNew}>
          <Plus className="h-3.5 w-3.5" /> {t('common.newProfile')}
        </Button>
      </div>
    </div>
  );
}
