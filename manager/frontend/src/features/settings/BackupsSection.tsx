import { useState } from 'react';
import { Download, RotateCcw, Trash2 } from 'lucide-react';
import type { BackupArchive } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { IconButton } from '@/components/ui/IconButton';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { formatBytes, formatDateTime, relativeTime } from '@/lib/format';
import { useT } from '@/i18n';
import { useBackups, useCreateBackup, useDeleteBackup, useRestoreBackup } from './api';

export function BackupsSection() {
  const t = useT();
  const backups = useBackups();
  const createBackup = useCreateBackup();
  const restoreBackup = useRestoreBackup();
  const deleteBackup = useDeleteBackup();
  const [restoreTarget, setRestoreTarget] = useState<BackupArchive | null>(null);
  const list = backups.data ?? [];

  return (
    <section className="rounded-lg border border-line bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-[15px] font-semibold text-ink">{t('bkp.title')}</h2>
          <p className="mt-0.5 text-2xs text-ink-faint">{t('bkp.desc')}</p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => createBackup.mutate()}
          loading={createBackup.isPending}
        >
          <Download className="h-3.5 w-3.5" /> {t('bkp.now')}
        </Button>
      </div>

      {list.length === 0 ? (
        <p className="mt-3 text-2xs text-ink-faint">{t('bkp.empty')}</p>
      ) : (
        <div className="mt-3 divide-y divide-line rounded-md border border-line">
          {list.map((backup) => (
            <div key={backup.id} className="flex items-center gap-3 px-3 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium text-ink">
                    {t('bkp.created', { time: relativeTime(backup.created_at) })}
                  </span>
                  <Badge tone="neutral">
                    {backup.automatic ? t('bkp.automatic') : t('bkp.manual')}
                  </Badge>
                  {backup.verified && <Badge tone="success">{t('bkp.verified')}</Badge>}
                </div>
                <p className="truncate text-2xs text-ink-faint">
                  {formatDateTime(backup.created_at)} · {formatBytes(backup.size_bytes)} ·{' '}
                  {backup.contents.join(', ')}
                </p>
              </div>
              <Button size="sm" variant="secondary" onClick={() => setRestoreTarget(backup)}>
                <RotateCcw className="h-3.5 w-3.5" /> {t('bkp.restore')}
              </Button>
              <IconButton size="sm" label={t('bkp.delete')} onClick={() => deleteBackup.mutate(backup.id)}>
                <Trash2 className="h-3.5 w-3.5" />
              </IconButton>
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={Boolean(restoreTarget)}
        onClose={() => setRestoreTarget(null)}
        onConfirm={() => {
          if (restoreTarget)
            restoreBackup.mutate(restoreTarget.id, { onSuccess: () => setRestoreTarget(null) });
        }}
        title={t('bkp.restore.title')}
        message={t('bkp.restore.msg', {
          date: restoreTarget ? formatDateTime(restoreTarget.created_at) : '',
        })}
        confirmLabel={t('bkp.restore.action')}
        loading={restoreBackup.isPending}
      />
    </section>
  );
}
