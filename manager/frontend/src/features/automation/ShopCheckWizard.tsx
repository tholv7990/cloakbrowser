import { useEffect, useMemo, useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { Modal } from '@/components/ui/Modal';
import { Field } from '@/components/ui/Field';
import { Input, Textarea } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Checkbox } from '@/components/ui/Checkbox';
import { Button } from '@/components/ui/Button';
import { useT } from '@/i18n';
import { useCreateShopCheckRun } from './api';
import { parseShopCheckEmails, workerCount } from './shopCheckInput';

const PER_OPTIONS = [1, 2, 3, 4, 5];
const PARALLEL_OPTIONS = [1, 2, 3, 4, 5];

/** Paste authorized accounts, tune grouping/concurrency, acknowledge, and
 * start a phone-OTP check. Counts preview live; the server re-validates. */
export function ShopCheckWizard({
  open,
  onClose,
  onStarted,
}: {
  open: boolean;
  onClose: () => void;
  onStarted: (runId: string) => void;
}) {
  const t = useT();
  const createRun = useCreateShopCheckRun();

  const [emailText, setEmailText] = useState('');
  const [perProfile, setPerProfile] = useState(5);
  const [maxParallel, setMaxParallel] = useState(3);
  const [region, setRegion] = useState('');
  const [prefix, setPrefix] = useState('');
  const [ack, setAck] = useState(false);
  const [regionError, setRegionError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setEmailText('');
      setPerProfile(5);
      setMaxParallel(3);
      setRegion('');
      setPrefix('');
      setAck(false);
      setRegionError(null);
    }
  }, [open]);

  // Live, client-side estimate. The backend's input_summary is authoritative.
  const parsed = useMemo(() => parseShopCheckEmails(emailText), [emailText]);
  const workers = workerCount(parsed.valid.length, perProfile);

  const regionValid = region === '' || /^[A-Za-z]{2}$/.test(region.trim());
  const canStart = parsed.valid.length > 0 && ack && regionValid && !createRun.isPending;

  const start = () => {
    if (region.trim() && !/^[A-Za-z]{2}$/.test(region.trim())) {
      setRegionError(t('shopchk.wizard.regionInvalid'));
      return;
    }
    createRun.mutate(
      {
        email_text: emailText,
        emails_per_profile: perProfile,
        max_parallel: maxParallel,
        region: region.trim() ? region.trim().toUpperCase() : null,
        profile_prefix: prefix.trim() || null,
        authorized_only_ack: ack,
      },
      {
        onSuccess: (result) => {
          onStarted(result.run.id);
          onClose();
        },
      },
    );
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={t('shopchk.wizard.title')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" onClick={start} loading={createRun.isPending} disabled={!canStart}>
            <ShieldCheck className="h-3.5 w-3.5" /> {t('shopchk.wizard.start')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field
          label={t('shopchk.wizard.emails')}
          hint={t('shopchk.wizard.emailsHint')}
          htmlFor="shop-emails"
        >
          <Textarea
            id="shop-emails"
            rows={7}
            value={emailText}
            onChange={(e) => setEmailText(e.target.value)}
            placeholder={'alice@example.com\nbob@example.com'}
            className="font-mono"
          />
        </Field>

        {/* Live counts — valid / duplicates / invalid + computed workers. */}
        <div className="flex flex-wrap gap-2 text-2xs">
          <Stat label={t('shopchk.wizard.valid')} value={parsed.valid.length} tone="ok" />
          <Stat label={t('shopchk.wizard.duplicates')} value={parsed.duplicates.length} tone="muted" />
          <Stat label={t('shopchk.wizard.invalid')} value={parsed.invalid.length} tone="warn" />
          <Stat label={t('shopchk.wizard.workers')} value={workers} tone="muted" />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label={t('shopchk.wizard.perProfile')} hint={t('shopchk.wizard.perProfileHint')}>
            <Select
              value={String(perProfile)}
              onChange={(e) => setPerProfile(Number(e.target.value))}
              options={PER_OPTIONS.map((n) => ({ value: String(n), label: String(n) }))}
            />
          </Field>
          <Field label={t('shopchk.wizard.maxParallel')} hint={t('shopchk.wizard.maxParallelHint')}>
            <Select
              value={String(maxParallel)}
              onChange={(e) => setMaxParallel(Number(e.target.value))}
              options={PARALLEL_OPTIONS.map((n) => ({ value: String(n), label: String(n) }))}
            />
          </Field>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field
            label={t('shopchk.wizard.region')}
            hint={t('shopchk.wizard.regionHint')}
            error={regionError}
          >
            <Input
              value={region}
              maxLength={2}
              onChange={(e) => {
                setRegion(e.target.value);
                setRegionError(null);
              }}
              placeholder={t('shopchk.wizard.regionPlaceholder')}
            />
          </Field>
          <Field label={t('shopchk.wizard.prefix')} hint={t('shopchk.wizard.prefixHint')}>
            <Input
              value={prefix}
              maxLength={80}
              onChange={(e) => setPrefix(e.target.value)}
              placeholder="ShopCheck"
            />
          </Field>
        </div>

        {/* 711 proxies + app-managed export are informational: nothing to enter. */}
        <p className="rounded-md border border-line bg-surface-sunken px-3 py-2 text-2xs text-ink-muted">
          {t('shopchk.wizard.proxyNote')}
        </p>

        <label className="flex cursor-pointer items-start gap-2 rounded-md border border-line p-3">
          <Checkbox checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5" />
          <span className="text-2xs text-ink-muted">{t('shopchk.wizard.ack')}</span>
        </label>
      </div>
    </Modal>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: 'ok' | 'warn' | 'muted' }) {
  const color =
    tone === 'ok' ? 'text-success' : tone === 'warn' ? 'text-warning' : 'text-ink-muted';
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-line bg-surface px-2 py-1">
      <span className={`font-semibold tabular-nums ${color}`}>{value}</span>
      <span className="text-ink-faint">{label}</span>
    </span>
  );
}
