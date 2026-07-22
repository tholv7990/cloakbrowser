import { useEffect, useState } from 'react';
import type { ProfileView } from '@/types/api';
import { Plus } from 'lucide-react';
import { useT } from '@/i18n';
import { TagChip } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Checkbox } from '@/components/ui/Checkbox';
import { Popover } from '@/components/ui/Popover';
import { useCreateTag, useTags } from '@/hooks/useReferenceData';
import { shortId } from '@/lib/format';
import { cn } from '@/lib/cn';
import { useUpdateProfileInline } from './api';

const TAG_COLORS = ['#2F6FEB', '#35B06E', '#E0A02E', '#E46076', '#8B5CF6', '#0E6FC2'];

const inlineInput =
  'w-full rounded border border-line-strong bg-surface-sunken px-1.5 py-0.5 text-ink ' +
  'focus:border-accent focus:outline-none focus:shadow-focus';

/** Name (with the identity glyph + short id) — click to rename inline. */
export function EditableNameCell({ profile }: { profile: ProfileView }) {
  const t = useT();
  const update = useUpdateProfileInline();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(profile.name);

  useEffect(() => {
    if (!editing) setValue(profile.name);
  }, [profile.name, editing]);

  const commit = () => {
    const trimmed = value.trim();
    setEditing(false);
    if (trimmed && trimmed !== profile.name) {
      update.mutate({ read: profile.read, changes: { name: trimmed } });
    } else {
      setValue(profile.name);
    }
  };

  return (
    <div className="min-w-0">
      {editing ? (
        <input
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onFocus={(e) => e.currentTarget.select()}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit();
            if (e.key === 'Escape') {
              setValue(profile.name);
              setEditing(false);
            }
          }}
          aria-label={t('editor.name')}
          className={cn(inlineInput, 'text-[13px] font-medium')}
        />
      ) : (
        <button
          type="button"
          onClick={() => setEditing(true)}
          title={t('cell.clickRename')}
          className="block max-w-full truncate text-left text-[13px] font-medium text-ink hover:text-accent"
        >
          {profile.name}
        </button>
      )}
      <div className="data truncate text-[11px] text-ink-faint">{shortId(profile.id)}</div>
    </div>
  );
}

/** Notes — click to edit inline (blur or Ctrl/⌘+Enter saves, Esc cancels). */
export function EditableNotesCell({ profile }: { profile: ProfileView }) {
  const t = useT();
  const update = useUpdateProfileInline();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(profile.notes);

  useEffect(() => {
    if (!editing) setValue(profile.notes);
  }, [profile.notes, editing]);

  const commit = () => {
    setEditing(false);
    if (value !== profile.notes) update.mutate({ read: profile.read, changes: { notes: value } });
  };

  if (editing) {
    return (
      <textarea
        autoFocus
        rows={2}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setValue(profile.notes);
            setEditing(false);
          }
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) commit();
        }}
        aria-label={t('editor.notes')}
        maxLength={4000}
        className={cn(inlineInput, 'resize-none text-[12px] leading-snug')}
      />
    );
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      title={t('cell.clickEditNote')}
      className="w-full text-left"
    >
      {profile.notes ? (
        <span className="line-clamp-2 text-[12px] text-ink-muted">{profile.notes}</span>
      ) : (
        <span className="text-[12px] text-ink-faint hover:text-ink">{t('cell.addNote')}</span>
      )}
    </button>
  );
}

/** Tags — click opens a popover to toggle tags; each change saves the full set. */
export function TagsCell({ profile }: { profile: ProfileView }) {
  const t = useT();
  const tags = useTags();
  const createTag = useCreateTag();
  const update = useUpdateProfileInline();
  const selected = profile.read.tag_ids;
  const [draft, setDraft] = useState('');

  const toggle = (id: string) => {
    const next = selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id];
    update.mutate({ read: profile.read, changes: { tag_ids: next } });
  };

  const createAndApply = async () => {
    const name = draft.trim();
    if (!name || createTag.isPending) return;
    const color = TAG_COLORS[(tags.data?.length ?? 0) % TAG_COLORS.length];
    const tag = await createTag.mutateAsync({ name, color });
    setDraft('');
    if (!selected.includes(tag.id)) {
      update.mutate({ read: profile.read, changes: { tag_ids: [...selected, tag.id] } });
    }
  };

  return (
    <Popover
      align="start"
      width={220}
      trigger={
        <button
          type="button"
          title={t('cell.clickEditTags')}
          className="flex w-full flex-wrap items-center gap-1 text-left"
        >
          {profile.tags.length > 0 ? (
            <>
              {profile.tags.slice(0, 3).map((tag) => (
                <TagChip key={tag.id} name={tag.name} color={tag.color} />
              ))}
              {profile.tags.length > 3 && (
                <span className="text-2xs text-ink-faint">+{profile.tags.length - 3}</span>
              )}
            </>
          ) : (
            <span className="text-[12px] text-ink-faint hover:text-ink">{t('cell.addTags')}</span>
          )}
        </button>
      }
    >
      <div className="space-y-0.5">
        <p className="px-1 pb-1 text-[13px] font-semibold text-ink">{t('editor.tags')}</p>
        {(tags.data ?? []).map((tag) => (
          <label
            key={tag.id}
            className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 hover:bg-surface-sunken"
          >
            <Checkbox checked={selected.includes(tag.id)} onChange={() => toggle(tag.id)} />
            <TagChip name={tag.name} color={tag.color} />
          </label>
        ))}
        {(tags.data ?? []).length === 0 && (
          <p className="px-1 pb-1 text-2xs text-ink-faint">{t('cell.noTagsYet')}</p>
        )}
        <div className="mt-1 flex items-center gap-1.5 border-t border-line pt-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                void createAndApply();
              }
            }}
            placeholder={t('cell.newTag')}
            aria-label={t('cell.newTagName')}
            maxLength={80}
            className={cn(inlineInput, 'h-8 text-[13px]')}
          />
          <Button
            size="sm"
            variant="secondary"
            onClick={createAndApply}
            loading={createTag.isPending}
            disabled={!draft.trim()}
          >
            <Plus className="h-3.5 w-3.5" /> {t('common.add')}
          </Button>
        </div>
      </div>
    </Popover>
  );
}
