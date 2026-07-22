import { useEffect, useState } from 'react';
import { Circle, Square } from 'lucide-react';
import { Modal } from '@/components/ui/Modal';
import { Field } from '@/components/ui/Field';
import { Input, Textarea } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Button } from '@/components/ui/Button';
import { Spinner } from '@/components/ui/Spinner';
import { useProfiles } from '@/features/profiles/api';
import { useT } from '@/i18n';
import {
  useCancelRecording,
  useRecording,
  useStartRecording,
  useStopRecording,
} from './api';

/** Pick a profile, act out the flow in its browser, stop to save a template. */
export function RecordDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT();
  const profiles = useProfiles({ page: 1, page_size: 100, sort: 'name' });
  const start = useStartRecording();
  const stop = useStopRecording();
  const cancel = useCancelRecording();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [profileId, setProfileId] = useState('');
  const [recordingId, setRecordingId] = useState<string | null>(null);
  const recording = useRecording(recordingId);

  useEffect(() => {
    if (open) {
      setName('');
      setDescription('');
      setProfileId('');
      setRecordingId(null);
    }
  }, [open]);

  const isRecording = Boolean(recordingId);
  const stepCount = recording.data?.step_count ?? 0;
  const options = (profiles.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }));

  const begin = () => {
    if (!name.trim() || !profileId) return;
    start.mutate(
      { name: name.trim(), description: description.trim(), profile_id: profileId },
      { onSuccess: (rec) => setRecordingId(rec.id) },
    );
  };
  const finish = () => {
    if (!recordingId) return;
    stop.mutate(recordingId, {
      onSuccess: () => {
        setRecordingId(null);
        onClose();
      },
    });
  };
  const close = () => {
    if (recordingId) cancel.mutate(recordingId);
    setRecordingId(null);
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={close}
      title={t('auto.record.title')}
      description={t('auto.record.desc')}
      footer={
        isRecording ? (
          <>
            <Button variant="ghost" onClick={close}>
              {t('common.cancel')}
            </Button>
            <Button variant="primary" onClick={finish} loading={stop.isPending}>
              <Square className="h-3.5 w-3.5" /> {t('auto.record.stop')}
            </Button>
          </>
        ) : (
          <>
            <Button variant="ghost" onClick={close}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="primary"
              onClick={begin}
              loading={start.isPending}
              disabled={!name.trim() || !profileId}
            >
              <Circle className="h-3.5 w-3.5" /> {t('auto.record.start')}
            </Button>
          </>
        )
      }
    >
      {isRecording ? (
        <div className="space-y-3">
          <div className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger/5 px-3 py-2.5 text-[13px] text-ink">
            <span className="h-2 w-2 animate-pulse rounded-full bg-danger" />
            {t('auto.record.recording')}
          </div>
          <div className="flex items-center gap-2 text-2xs text-ink-muted">
            <Spinner /> {t('auto.record.stepsCaptured', { count: stepCount })}
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <Field label={t('auto.record.name')} required>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label={t('auto.record.profile')} required>
            <Select
              value={profileId}
              onChange={(e) => setProfileId(e.target.value)}
              placeholder={t('auto.record.chooseProfile')}
              options={options}
            />
          </Field>
          <Field label={t('auto.record.notes')}>
            <Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <p className="text-2xs text-ink-faint">{t('auto.record.hint')}</p>
        </div>
      )}
    </Modal>
  );
}
