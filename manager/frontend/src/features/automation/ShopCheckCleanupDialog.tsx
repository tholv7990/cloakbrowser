import { useEffect, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { Modal } from '@/components/ui/Modal';
import { Checkbox } from '@/components/ui/Checkbox';
import { Button } from '@/components/ui/Button';
import { useT } from '@/i18n';
import type { ShopCheckRunDetail } from '@/types/api';
import { useCleanupShopCheckRun } from './api';

/** Confirm deletion of a run's owned temporary profiles. The exact count shown
 * is echoed back to the server, which rejects a stale mismatch. */
export function ShopCheckCleanupDialog({
  run,
  open,
  onClose,
}: {
  run: ShopCheckRunDetail;
  open: boolean;
  onClose: () => void;
}) {
  const t = useT();
  const cleanup = useCleanupShopCheckRun();
  const [confirm, setConfirm] = useState(false);

  useEffect(() => {
    if (open) setConfirm(false);
  }, [open]);

  const ownedCount = run.workers.filter((w) => w.profile_id).length;

  const submit = () => {
    cleanup.mutate(
      { id: run.id, payload: { confirm: true, expected_profile_count: ownedCount } },
      { onSuccess: onClose },
    );
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      title={t('shopchk.cleanup.title')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="danger"
            onClick={submit}
            loading={cleanup.isPending}
            disabled={!confirm || cleanup.isPending}
          >
            <Trash2 className="h-3.5 w-3.5" /> {t('shopchk.cleanup.delete', { count: ownedCount })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-[13px] text-ink-muted">
          {t('shopchk.cleanup.body', { count: ownedCount })}
        </p>
        <p className="text-2xs text-ink-faint">{t('shopchk.cleanup.preserve')}</p>
        <label className="flex cursor-pointer items-start gap-2">
          <Checkbox checked={confirm} onChange={(e) => setConfirm(e.target.checked)} className="mt-0.5" />
          <span className="text-2xs text-ink-muted">{t('shopchk.cleanup.ack')}</span>
        </label>
      </div>
    </Modal>
  );
}
