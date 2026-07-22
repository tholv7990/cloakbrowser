import { useEffect, useState } from 'react';
import type { MediaAsset } from '@/types/api';
import { Modal } from '@/components/ui/Modal';
import { Checkbox } from '@/components/ui/Checkbox';
import { Button } from '@/components/ui/Button';
import { useProfiles } from '@/features/profiles/api';
import { useT } from '@/i18n';
import { useMediaAssignments, useSetMediaAssignments } from './api';

/** Pick which profiles use a media asset when injection is enabled. */
export function AssignMediaDialog({
  asset,
  onClose,
}: {
  asset: MediaAsset | null;
  onClose: () => void;
}) {
  const t = useT();
  const profiles = useProfiles({ page: 1, page_size: 100, sort: 'name' });
  const assignments = useMediaAssignments(asset?.id ?? null);
  const save = useSetMediaAssignments();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (asset && assignments.data) setSelected(new Set(assignments.data));
  }, [asset, assignments.data]);

  const items = profiles.data?.items ?? [];
  const toggle = (id: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const submit = () => {
    if (!asset) return;
    save.mutate(
      { assetId: asset.id, profileIds: [...selected] },
      { onSuccess: onClose },
    );
  };

  return (
    <Modal
      open={Boolean(asset)}
      onClose={onClose}
      title={t('media.assign.title', { name: asset?.name ?? '' })}
      description={t('media.assign.desc')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" onClick={submit} loading={save.isPending}>
            {t('media.assign.save')}
          </Button>
        </>
      }
    >
      {items.length === 0 ? (
        <p className="text-2xs text-ink-faint">{t('media.assign.noProfiles')}</p>
      ) : (
        <div className="space-y-2">
          <div className="max-h-64 space-y-0.5 overflow-auto rounded-md border border-line p-1">
            {items.map((profile) => (
              <label
                key={profile.id}
                className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 hover:bg-surface-sunken"
              >
                <Checkbox
                  checked={selected.has(profile.id)}
                  onChange={() => toggle(profile.id)}
                  aria-label={profile.name}
                />
                <span className="text-[13px] text-ink">{profile.name}</span>
              </label>
            ))}
          </div>
          <p className="text-2xs text-ink-faint">
            {t('media.assign.selected', { count: selected.size })}
          </p>
        </div>
      )}
    </Modal>
  );
}
