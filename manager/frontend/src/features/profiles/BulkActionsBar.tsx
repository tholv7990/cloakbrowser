import { CircleDot, FolderInput, Globe, Pin, PinOff, Tag as TagIcon, Trash2, X } from 'lucide-react';
import type { BulkProfileRequest, Folder, Tag, WorkflowStatus } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Menu, MenuGroup, MenuItem } from '@/components/ui/Menu';
import { useT } from '@/i18n';

export function BulkActionsBar({
  count,
  folders,
  statuses,
  tags,
  onAction,
  onAssignProxies,
  onClear,
}: {
  count: number;
  folders: Folder[];
  statuses: WorkflowStatus[];
  tags: Tag[];
  onAction: (action: Omit<BulkProfileRequest, 'ids'>) => void;
  onAssignProxies: () => void;
  onClear: () => void;
}) {
  const t = useT();
  if (count === 0) return null;
  return (
    <div className="flex items-center gap-3 border-b border-line bg-accent/5 px-4 py-2">
      <span className="text-[13px] font-medium text-ink">{t('bulk.selected', { count })}</span>
      <div className="flex items-center gap-1.5">
        <Button size="sm" variant="secondary" onClick={() => onAction({ action: 'pin' })}>
          <Pin className="h-3.5 w-3.5" /> {t('bulk.pin')}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => onAction({ action: 'unpin' })}>
          <PinOff className="h-3.5 w-3.5" /> {t('bulk.unpin')}
        </Button>
        <Menu
          align="start"
          width={220}
          trigger={
            <Button size="sm" variant="secondary">
              <FolderInput className="h-3.5 w-3.5" /> {t('bulk.moveFolder')}
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
        {statuses.length > 0 && (
          <Menu
            align="start"
            width={220}
            trigger={
              <Button size="sm" variant="secondary">
                <CircleDot className="h-3.5 w-3.5" /> {t('bulk.setStatus')}
              </Button>
            }
          >
            {statuses.map((status) => (
              <MenuItem
                key={status.id}
                onSelect={() => onAction({ action: 'set_status', workflow_status_id: status.id })}
              >
                {status.name}
              </MenuItem>
            ))}
          </Menu>
        )}
        {tags.length > 0 && (
          <Menu
            align="start"
            width={220}
            trigger={
              <Button size="sm" variant="secondary">
                <TagIcon className="h-3.5 w-3.5" /> {t('bulk.tags')}
              </Button>
            }
          >
            <MenuGroup label={t('bulk.addTag')}>
              {tags.map((tag) => (
                <MenuItem
                  key={`add-${tag.id}`}
                  onSelect={() => onAction({ action: 'add_tag', tag_id: tag.id })}
                >
                  {tag.name}
                </MenuItem>
              ))}
            </MenuGroup>
            <MenuGroup label={t('bulk.removeTag')}>
              {tags.map((tag) => (
                <MenuItem
                  key={`rm-${tag.id}`}
                  onSelect={() => onAction({ action: 'remove_tag', tag_id: tag.id })}
                >
                  {tag.name}
                </MenuItem>
              ))}
            </MenuGroup>
          </Menu>
        )}
        <Button size="sm" variant="secondary" onClick={onAssignProxies}>
          <Globe className="h-3.5 w-3.5" /> {t('bulk.assignProxies')}
        </Button>
        <Button size="sm" variant="danger" onClick={() => onAction({ action: 'trash' })}>
          <Trash2 className="h-3.5 w-3.5" /> {t('bulk.trash')}
        </Button>
      </div>
      <button
        type="button"
        onClick={onClear}
        className="ml-auto flex items-center gap-1 text-2xs text-ink-muted hover:text-ink"
      >
        <X className="h-3.5 w-3.5" /> {t('bulk.clear')}
      </button>
    </div>
  );
}
