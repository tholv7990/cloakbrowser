import { FolderInput, Pin, PinOff, Trash2, X } from 'lucide-react';
import type { BulkProfileRequest, Folder } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Menu, MenuItem } from '@/components/ui/Menu';

export function BulkActionsBar({
  count,
  folders,
  onAction,
  onClear,
}: {
  count: number;
  folders: Folder[];
  onAction: (action: Omit<BulkProfileRequest, 'ids'>) => void;
  onClear: () => void;
}) {
  if (count === 0) return null;
  return (
    <div className="flex items-center gap-3 border-b border-line bg-accent/5 px-4 py-2">
      <span className="text-[13px] font-medium text-ink">{count} selected</span>
      <div className="flex items-center gap-1.5">
        <Button size="sm" variant="secondary" onClick={() => onAction({ action: 'pin' })}>
          <Pin className="h-3.5 w-3.5" /> Pin
        </Button>
        <Button size="sm" variant="secondary" onClick={() => onAction({ action: 'unpin' })}>
          <PinOff className="h-3.5 w-3.5" /> Unpin
        </Button>
        <Menu
          align="start"
          width={220}
          trigger={
            <Button size="sm" variant="secondary">
              <FolderInput className="h-3.5 w-3.5" /> Move to folder
            </Button>
          }
        >
          {folders.map((folder) => (
            <MenuItem
              key={folder.id}
              onSelect={() => onAction({ action: 'move_folder', folder_id: folder.id })}
            >
              {folder.name}
            </MenuItem>
          ))}
        </Menu>
        <Button size="sm" variant="danger" onClick={() => onAction({ action: 'trash' })}>
          <Trash2 className="h-3.5 w-3.5" /> Move to trash
        </Button>
      </div>
      <button
        type="button"
        onClick={onClear}
        className="ml-auto flex items-center gap-1 text-2xs text-ink-muted hover:text-ink"
      >
        <X className="h-3.5 w-3.5" /> Clear selection
      </button>
    </div>
  );
}
