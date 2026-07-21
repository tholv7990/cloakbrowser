import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { RowSelectionState } from '@tanstack/react-table';
import { Users } from 'lucide-react';
import type { BulkProfileRequest, ProfileListParams, ProfileSort, ProfileView } from '@/types/api';
import { api } from '@/api';
import { useAppData } from '@/hooks/useAppData';
import { useDebounce } from '@/hooks/useDebounce';
import { useUiStore } from '@/app/uiStore';
import { useRuntimeStore } from '@/app/runtimeStore';
import { useT } from '@/i18n';
import { useToast } from '@/components/ui/Toast';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Textarea } from '@/components/ui/Input';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/states';
import { useProxies } from '@/features/proxies/api';
import { useProfiles, usePinToggle, useBulkAction, useQuickCreate } from './api';
import { ProfilesToolbar } from './ProfilesToolbar';
import { ProfilesTabs, type ProfileTab } from './ProfilesTabs';
import { ProfilesTable } from './ProfilesTable';
import { ProfilesPagination } from './ProfilesPagination';
import { BulkActionsBar } from './BulkActionsBar';
import { ProfileDialogs } from './ProfileDialogs';
import type { RowDialog } from './ProfileRowActions';
import { buildProfileViews } from './view';
import { DEFAULT_SORT, emptyFilters, nextSort, type ProfileFilters } from './types';

export function ProfilesPage() {
  const t = useT();
  const app = useAppData();
  const folders = app.folders;
  const tags = app.tags;
  const statuses = app.statuses;
  const proxies = useProxies().data ?? [];
  const profileRoot = app.profileRoot;

  const rowsPerPage = useUiStore((state) => state.rowsPerPage);
  const setRowsPerPage = useUiStore((state) => state.setRowsPerPage);

  const [searchInput, setSearchInput] = useState('');
  const search = useDebounce(searchInput, 300);
  const [filters, setFilters] = useState<ProfileFilters>(emptyFilters);
  const [tab, setTab] = useState<ProfileTab>({ kind: 'all' });
  const [sort, setSort] = useState<ProfileSort>(DEFAULT_SORT);
  const [page, setPage] = useState(1);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [dialog, setDialog] = useState<{ type: RowDialog; profile: ProfileView } | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  // Any change to the result shape resets to page 1.
  useEffect(() => setPage(1), [search, filters, tab, rowsPerPage]);

  const effectiveSort: ProfileSort = tab.kind === 'recent' ? '-last_opened_at' : sort;
  const params: ProfileListParams = {
    query: search || undefined,
    sort: effectiveSort,
    page,
    page_size: rowsPerPage,
    folder_id: tab.kind === 'folder' ? tab.id : (filters.folder_id ?? undefined),
    tag_id: filters.tag_id ?? undefined,
    workflow_status_id: filters.workflow_status_id ?? undefined,
    pinned: tab.kind === 'pinned' ? true : (filters.pinned ?? undefined),
  };

  const query = useProfiles(params);
  const pinToggle = usePinToggle();
  const bulk = useBulkAction();
  const quickCreate = useQuickCreate();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const importProfile = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api.importProfile(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      setImportOpen(false);
      toast({ title: 'Profile imported', tone: 'success' });
    },
    onError: (error) =>
      toast({ title: 'Import failed', description: (error as Error).message, tone: 'danger' }),
  });

  const messages = useRuntimeStore((state) => state.messages);
  const selectedIds = Object.keys(rowSelection).filter((id) => rowSelection[id]);
  const items = query.data?.items ?? [];
  const views = useMemo(
    () => buildProfileViews(items, { tags, statuses, proxies }, messages),
    [items, tags, statuses, proxies, messages],
  );
  const total = query.data?.total ?? 0;
  const totalPages = query.data?.pages ?? 1;

  const handleBulk = (action: Omit<BulkProfileRequest, 'ids'>) => {
    bulk.mutate({ ...action, ids: selectedIds } as BulkProfileRequest, {
      onSuccess: () => setRowSelection({}),
    });
  };

  const handleExport = () => {
    const blob = new Blob([JSON.stringify({ schema_version: 1, profiles: items }, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'cloakbrowser-profiles.json';
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const filtersActive =
    search !== '' || Object.values(filters).some((v) => v !== null) || tab.kind !== 'all';

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-3 border-b border-line px-4 pb-3 pt-4">
        <ProfilesToolbar
          search={searchInput}
          onSearch={setSearchInput}
          filters={filters}
          onFilters={setFilters}
          folders={folders}
          tags={tags}
          statuses={statuses}
          onQuickCreate={() => quickCreate.mutate()}
          quickCreating={quickCreate.isPending}
          onImport={() => setImportOpen(true)}
          onExport={handleExport}
        />
        <ProfilesTabs active={tab} onChange={setTab} folders={folders} total={total} />
      </div>

      <BulkActionsBar
        count={selectedIds.length}
        folders={folders}
        onAction={handleBulk}
        onClear={() => setRowSelection({})}
      />

      <div className="min-h-0 flex-1 overflow-y-auto">
        {query.isLoading || app.isLoading ? (
          <LoadingBlock label="Loading profiles…" />
        ) : query.isError ? (
          <ErrorState
            title="Could not load profiles"
            message={(query.error as Error).message}
            onRetry={() => query.refetch()}
          />
        ) : items.length === 0 ? (
          filtersActive ? (
            <EmptyState
              icon={<Users className="h-5 w-5" />}
              title={t('profiles.noMatch.title')}
              description={t('profiles.noMatch.desc')}
              action={
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setSearchInput('');
                    setFilters(emptyFilters);
                    setTab({ kind: 'all' });
                  }}
                >
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={<Users className="h-5 w-5" />}
              title={t('profiles.empty.title')}
              description={t('profiles.empty.desc')}
              action={
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => quickCreate.mutate()}
                  loading={quickCreate.isPending}
                >
                  Quick create a profile
                </Button>
              }
            />
          )
        ) : (
          <ProfilesTable
            data={views}
            sort={effectiveSort}
            onToggleSort={(columnId) => setSort((current) => nextSort(current, columnId))}
            rowSelection={rowSelection}
            onRowSelectionChange={setRowSelection}
            onDialog={(type, profile) => setDialog({ type, profile })}
            onTogglePin={(profile) => pinToggle.mutate({ id: profile.id, pinned: !profile.pinned })}
            profileRoot={profileRoot}
          />
        )}
      </div>

      <ProfilesPagination
        page={page}
        pageSize={rowsPerPage}
        total={total}
        totalPages={totalPages}
        onPage={setPage}
        onPageSize={setRowsPerPage}
      />

      <ProfileDialogs
        dialog={dialog}
        onClose={() => setDialog(null)}
        folders={folders}
        proxies={proxies}
      />

      <ImportProfileModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        loading={importProfile.isPending}
        onImport={(payload) => importProfile.mutate(payload)}
      />
    </div>
  );
}

function ImportProfileModal({
  open,
  onClose,
  loading,
  onImport,
}: {
  open: boolean;
  onClose: () => void;
  loading: boolean;
  onImport: (payload: Record<string, unknown>) => void;
}) {
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    try {
      const parsed = JSON.parse(text) as Record<string, unknown>;
      setError(null);
      onImport(parsed);
    } catch {
      setError('That is not valid JSON. Paste an exported .cloakprofile.json file.');
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Import profile"
      description="Paste an exported profile configuration (no secrets are included)."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={!text.trim()} loading={loading}>
            Import
          </Button>
        </>
      }
    >
      <Textarea
        rows={10}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder='{"schema_version": 1, "profile": { … }}'
        className="font-mono text-[12px]"
        invalid={Boolean(error)}
      />
      {error && <p className="mt-2 text-2xs text-danger">{error}</p>}
    </Modal>
  );
}
