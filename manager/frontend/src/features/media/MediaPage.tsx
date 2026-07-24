import { useState } from 'react';
import { Camera, Mic, Monitor, Plus, Trash2, Users } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { MediaAsset, MediaKind } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { IconButton } from '@/components/ui/IconButton';
import { Toggle } from '@/components/ui/Toggle';
import { Modal } from '@/components/ui/Modal';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/states';
import { formatBytes } from '@/lib/format';
import { useT, type TranslationKey } from '@/i18n';
import {
  useCreateMediaAsset,
  useDeleteMediaAsset,
  useMediaAssets,
  useMediaSettings,
  useUpdateMediaSettings,
} from './api';
import { AssignMediaDialog } from './AssignMediaDialog';

const KIND_ICON: Record<MediaKind, LucideIcon> = {
  camera: Camera,
  microphone: Mic,
  screen: Monitor,
};

export function MediaPage() {
  const t = useT();
  const settings = useMediaSettings();
  const updateSettings = useUpdateMediaSettings();
  const assets = useMediaAssets();
  const createAsset = useCreateMediaAsset();
  const deleteAsset = useDeleteMediaAsset();

  const [addOpen, setAddOpen] = useState(false);
  const [assignAsset, setAssignAsset] = useState<MediaAsset | null>(null);
  const [name, setName] = useState('');
  const [kind, setKind] = useState<MediaKind>('camera');
  const [format, setFormat] = useState('image/jpeg');
  const list = assets.data ?? [];

  const submit = () => {
    if (!name.trim()) return;
    createAsset.mutate(
      { name: name.trim(), kind, format: format.trim() || 'image/jpeg' },
      {
        onSuccess: () => {
          setAddOpen(false);
          setName('');
        },
      },
    );
  };

  return (
    // The app shell's <main> is overflow-hidden, so each page owns its scroll.
    <div className="h-full overflow-y-auto">
    <div className="mx-auto max-w-4xl space-y-4 px-5 py-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[13px] text-ink-muted">{t('media.subtitle')}</p>
        <Button variant="primary" size="sm" onClick={() => setAddOpen(true)}>
          <Plus className="h-3.5 w-3.5" /> {t('media.add')}
        </Button>
      </div>

      <div className="flex items-center justify-between rounded-md border border-line bg-surface-sunken px-3 py-2.5">
        <span className="text-[13px] text-ink">{t('media.enabled')}</span>
        <Toggle
          checked={settings.data?.enabled ?? false}
          onChange={(value) => updateSettings.mutate({ enabled: value })}
          label={t('media.enabled')}
        />
      </div>

      {assets.isLoading ? (
        <LoadingBlock label="…" />
      ) : assets.isError ? (
        <ErrorState message={(assets.error as Error).message} onRetry={() => assets.refetch()} />
      ) : list.length === 0 ? (
        <EmptyState
          icon={<Camera className="h-5 w-5" />}
          title={t('media.empty.title')}
          description={t('media.empty.desc')}
          action={
            <Button variant="primary" size="sm" onClick={() => setAddOpen(true)}>
              <Plus className="h-3.5 w-3.5" /> {t('media.add')}
            </Button>
          }
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-2xs uppercase tracking-wide text-ink-faint">
                <th className="px-3 py-2 text-left font-semibold">{t('media.col.name')}</th>
                <th className="px-3 py-2 text-left font-semibold">{t('media.col.kind')}</th>
                <th className="px-3 py-2 text-left font-semibold">{t('media.col.format')}</th>
                <th className="px-3 py-2 text-right font-semibold">{t('media.col.size')}</th>
                <th className="px-3 py-2 text-right font-semibold">{t('media.col.assigned')}</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {list.map((asset) => {
                const Icon = KIND_ICON[asset.kind];
                return (
                  <tr key={asset.id} className="border-b border-line/60 hover:bg-surface-sunken/50">
                    <td className="px-3 py-2 text-[13px] font-medium text-ink">{asset.name}</td>
                    <td className="px-3 py-2">
                      <Badge tone="neutral">
                        <Icon className="h-3 w-3" /> {t(`media.kind.${asset.kind}` as TranslationKey)}
                      </Badge>
                    </td>
                    <td className="data px-3 py-2 text-[12px] text-ink-muted">{asset.format}</td>
                    <td className="px-3 py-2 text-right text-[12px] tabular-nums text-ink-muted">
                      {formatBytes(asset.size_bytes)}
                    </td>
                    <td className="px-3 py-2 text-right text-[12px] text-ink-muted">
                      {t('media.assignedCount', { count: asset.assigned_profile_count })}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="flex items-center justify-end gap-0.5">
                        <IconButton
                          size="sm"
                          label={t('media.assign')}
                          onClick={() => setAssignAsset(asset)}
                        >
                          <Users className="h-3.5 w-3.5" />
                        </IconButton>
                        <IconButton
                          size="sm"
                          label={t('media.delete')}
                          onClick={() => deleteAsset.mutate(asset.id)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </IconButton>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title={t('media.add.title')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setAddOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button variant="primary" onClick={submit} loading={createAsset.isPending} disabled={!name.trim()}>
              {t('media.add')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label={t('media.add.name')} required>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label={t('media.add.kind')}>
            <Select
              value={kind}
              onChange={(e) => setKind(e.target.value as MediaKind)}
              options={[
                { value: 'camera', label: t('media.kind.camera') },
                { value: 'microphone', label: t('media.kind.microphone') },
                { value: 'screen', label: t('media.kind.screen') },
              ]}
            />
          </Field>
          <Field label={t('media.add.format')}>
            <Input mono value={format} onChange={(e) => setFormat(e.target.value)} />
          </Field>
        </div>
      </Modal>

      <AssignMediaDialog asset={assignAsset} onClose={() => setAssignAsset(null)} />
    </div>
    </div>
  );
}
