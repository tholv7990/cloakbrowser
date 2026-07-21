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
import {
  useCreateFolder,
  useDeleteFolder,
  useFolders,
  useRenameFolder,
  useReorderFolders,
} from './api';

export function FoldersPage() {
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
    <div className="mx-auto max-w-3xl px-5 py-6">
      <p className="mb-4 text-[13px] text-ink-muted">
        Group profiles into folders. A profile belongs to one folder; deleting a folder keeps its
        profiles and leaves them unfiled.
      </p>

      <div className="mb-5 flex gap-2">
        <Input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submitNew()}
          placeholder="New folder name"
          aria-label="New folder name"
        />
        <Button
          variant="primary"
          onClick={submitNew}
          loading={createFolder.isPending}
          disabled={!newName.trim()}
        >
          <Plus className="h-4 w-4" /> Add folder
        </Button>
      </div>

      {folders.isLoading ? (
        <LoadingBlock label="Loading folders…" />
      ) : folders.isError ? (
        <ErrorState message={(folders.error as Error).message} onRetry={() => folders.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<FolderClosed className="h-5 w-5" />}
          title="No folders yet"
          description="Create a folder above to start organizing profiles."
        />
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {items.map((folder, index) => (
            <li key={folder.id} className="flex items-center gap-3 px-3 py-2.5">
              <div className="flex flex-col">
                <button
                  type="button"
                  aria-label={`Move ${folder.name} up`}
                  disabled={index === 0}
                  onClick={() => move(index, -1)}
                  className="text-ink-faint hover:text-ink disabled:opacity-30"
                >
                  <ArrowUp className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  aria-label={`Move ${folder.name} down`}
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
                    aria-label={`Rename ${folder.name}`}
                  />
                  <IconButton
                    size="sm"
                    label="Save name"
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
                  <IconButton size="sm" label="Cancel" onClick={() => setEditing(null)}>
                    <X className="h-4 w-4" />
                  </IconButton>
                </div>
              ) : (
                <>
                  <span className="flex-1 text-[13px] font-medium text-ink">{folder.name}</span>
                  <div className="flex items-center gap-3 text-2xs text-ink-muted">
                    <span>{folder.profile_count ?? 0} profiles</span>
                    {(folder.running_count ?? 0) > 0 && (
                      <Badge tone="success">
                        <StatusDot tone="success" pulse /> {folder.running_count} running
                      </Badge>
                    )}
                  </div>
                  <IconButton
                    size="sm"
                    label={`Rename ${folder.name}`}
                    onClick={() => setEditing({ id: folder.id, name: folder.name })}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </IconButton>
                  <IconButton
                    size="sm"
                    label={`Delete ${folder.name}`}
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
        title="Delete folder?"
        message={`"${toDelete?.name}" will be removed. Its ${toDelete?.profile_count ?? 0} profile(s) are kept and become unfiled.`}
        confirmLabel="Delete folder"
        tone="danger"
        loading={deleteFolder.isPending}
      />
    </div>
  );
}
