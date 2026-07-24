import { useState } from 'react';
import { ArrowDown, ArrowUp, Check, FolderClosed, Pencil, Plus, Trash2, X } from 'lucide-react';
import type { Folder } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { IconButton } from '@/components/ui/IconButton';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/states';
import { StatusDot } from '@/components/ui/Badge';
import { useT } from '@/i18n';
import {
  useCreateFolder,
  useDeleteFolder,
  useFolders,
  useRenameFolder,
  useReorderFolders,
} from './api';

export function FoldersPage() {
  const t = useT();
  const folders = useFolders();
  const createFolder = useCreateFolder();
  const renameFolder = useRenameFolder();
  const reorderFolders = useReorderFolders();
  const deleteFolder = useDeleteFolder();

  const [newName, setNewName] = useState('');
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null);
  const [toDelete, setToDelete] = useState<Folder | null>(null);

  const items = [...(folders.data ?? [])].sort((a, b) => a.position - b.position);

  const move = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= items.length) return;
    const ids = items.map((f) => f.id);
    [ids[index], ids[target]] = [ids[target], ids[index]];
    reorderFolders.mutate(ids);
  };

  const submitNew = () => {
    if (!newName.trim()) return;
    createFolder.mutate(newName.trim(), { onSuccess: () => setNewName('') });
  };

  return (
    // The app shell's <main> is overflow-hidden, so each page owns its scroll.
    <div className="h-full overflow-y-auto">
    <div className="mx-auto max-w-3xl px-5 py-6">
      <p className="mb-4 text-[13px] text-ink-muted">{t('folders.desc')}</p>

      <div className="mb-5 flex gap-2">
        <Input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submitNew()}
          placeholder={t('folders.newName')}
          aria-label={t('folders.newName')}
        />
        <Button
          variant="primary"
          onClick={submitNew}
          loading={createFolder.isPending}
          disabled={!newName.trim()}
        >
          <Plus className="h-4 w-4" /> {t('folders.add')}
        </Button>
      </div>

      {folders.isLoading ? (
        <LoadingBlock label={t('folders.loading')} />
      ) : folders.isError ? (
        <ErrorState message={(folders.error as Error).message} onRetry={() => folders.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<FolderClosed className="h-5 w-5" />}
          title={t('folders.empty.title')}
          description={t('folders.empty.desc')}
        />
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {items.map((folder, index) => (
            <li key={folder.id} className="flex items-center gap-3 px-3 py-2.5">
              <div className="flex flex-col">
                <button
                  type="button"
                  aria-label={t('folders.moveUp', { name: folder.name })}
                  disabled={index === 0}
                  onClick={() => move(index, -1)}
                  className="text-ink-faint hover:text-ink disabled:opacity-30"
                >
                  <ArrowUp className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  aria-label={t('folders.moveDown', { name: folder.name })}
                  disabled={index === items.length - 1}
                  onClick={() => move(index, 1)}
                  className="text-ink-faint hover:text-ink disabled:opacity-30"
                >
                  <ArrowDown className="h-3.5 w-3.5" />
                </button>
              </div>

              <FolderClosed className="h-4 w-4 text-ink-faint" />

              {editing?.id === folder.id ? (
                <div className="flex flex-1 items-center gap-2">
                  <Input
                    autoFocus
                    value={editing.name}
                    onChange={(e) => setEditing({ id: folder.id, name: e.target.value })}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && editing.name.trim()) {
                        renameFolder.mutate(
                          { id: folder.id, name: editing.name.trim() },
                          { onSuccess: () => setEditing(null) },
                        );
                      }
                      if (e.key === 'Escape') setEditing(null);
                    }}
                    aria-label={t('folders.renameLabel', { name: folder.name })}
                  />
                  <IconButton
                    size="sm"
                    label={t('folders.saveName')}
                    onClick={() =>
                      editing.name.trim() &&
                      renameFolder.mutate(
                        { id: folder.id, name: editing.name.trim() },
                        { onSuccess: () => setEditing(null) },
                      )
                    }
                  >
                    <Check className="h-4 w-4" />
                  </IconButton>
                  <IconButton size="sm" label={t('common.cancel')} onClick={() => setEditing(null)}>
                    <X className="h-4 w-4" />
                  </IconButton>
                </div>
              ) : (
                <>
                  <span className="flex-1 text-[13px] font-medium text-ink">{folder.name}</span>
                  <div className="flex items-center gap-3 text-2xs text-ink-muted">
                    <span>{t('folders.profiles', { count: folder.profile_count ?? 0 })}</span>
                    {(folder.running_count ?? 0) > 0 && (
                      <Badge tone="success">
                        <StatusDot tone="success" pulse />{' '}
                        {t('folders.running', { count: folder.running_count ?? 0 })}
                      </Badge>
                    )}
                  </div>
                  <IconButton
                    size="sm"
                    label={t('folders.renameLabel', { name: folder.name })}
                    onClick={() => setEditing({ id: folder.id, name: folder.name })}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </IconButton>
                  <IconButton
                    size="sm"
                    label={t('folders.deleteLabel', { name: folder.name })}
                    onClick={() => setToDelete(folder)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </IconButton>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={Boolean(toDelete)}
        onClose={() => setToDelete(null)}
        onConfirm={() =>
          toDelete && deleteFolder.mutate(toDelete.id, { onSuccess: () => setToDelete(null) })
        }
        title={t('folders.delete.title')}
        message={t('folders.delete.message', {
          name: toDelete?.name ?? '',
          count: toDelete?.profile_count ?? 0,
        })}
        confirmLabel={t('folders.delete.action')}
        tone="danger"
        loading={deleteFolder.isPending}
      />
    </div>
    </div>
  );
}
