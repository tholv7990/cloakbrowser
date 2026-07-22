import { useState } from 'react';
import { Factory } from 'lucide-react';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Toggle } from '@/components/ui/Toggle';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { useT } from '@/i18n';
import { useCancelFactoryJob, useFactoryJobs, useStartFactoryJob, useTemplates } from './api';

export function FactoryPanel() {
  const t = useT();
  const templates = useTemplates();
  const jobs = useFactoryJobs();
  const startJob = useStartFactoryJob();
  const cancelJob = useCancelFactoryJob();

  const [quantity, setQuantity] = useState(5);
  const [namePrefix, setNamePrefix] = useState('batch');
  const [templateId, setTemplateId] = useState('');
  const [startAutomation, setStartAutomation] = useState(false);

  const submit = () =>
    startJob.mutate({
      quantity,
      name_prefix: namePrefix.trim() || 'batch',
      automation_template_id: startAutomation && templateId ? templateId : null,
      start_automation: startAutomation && Boolean(templateId),
    });

  const templateOptions = [
    { value: '', label: '—' },
    ...(templates.data ?? []).map((x) => ({ value: x.id, label: x.name })),
  ];

  return (
    <section className="space-y-4">
      <div>
        <div className="mb-1 flex items-center gap-1.5 text-ink">
          <Factory className="h-4 w-4 text-accent" />
          <h2 className="font-display text-[15px] font-semibold">{t('auto.factory.title')}</h2>
        </div>
        <p className="text-2xs text-ink-faint">{t('auto.factory.desc')}</p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label={t('auto.factory.quantity')}>
          <Input
            type="number"
            value={quantity}
            onChange={(e) => setQuantity(Math.max(1, Math.min(50, Number(e.target.value))))}
          />
        </Field>
        <Field label={t('auto.factory.namePrefix')}>
          <Input value={namePrefix} onChange={(e) => setNamePrefix(e.target.value)} />
        </Field>
      </div>
      <div className="flex items-center justify-between rounded-md border border-line bg-surface-sunken px-3 py-2.5">
        <span className="text-[13px] text-ink">{t('auto.factory.startAutomation')}</span>
        <Toggle
          checked={startAutomation}
          onChange={setStartAutomation}
          label={t('auto.factory.startAutomation')}
        />
      </div>
      {startAutomation && (
        <Field label={t('auto.factory.template')}>
          <Select
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
            options={templateOptions}
          />
        </Field>
      )}
      <Button variant="primary" onClick={submit} loading={startJob.isPending}>
        <Factory className="h-3.5 w-3.5" /> {t('auto.factory.start')}
      </Button>

      {(jobs.data ?? []).length === 0 ? (
        <p className="text-2xs text-ink-faint">{t('auto.factory.empty')}</p>
      ) : (
        <div className="divide-y divide-line rounded-md border border-line">
          {(jobs.data ?? []).map((job) => (
            <div key={job.id} className="flex items-center justify-between gap-3 px-3 py-2.5">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium text-ink">{job.name_prefix}</span>
                  <Badge
                    tone={
                      job.status === 'completed'
                        ? 'success'
                        : job.status === 'running'
                          ? 'info'
                          : 'neutral'
                    }
                  >
                    {job.status}
                  </Badge>
                </div>
                <p className="text-2xs text-ink-faint">
                  {t('auto.factory.created', { created: job.created_count, quantity: job.quantity })}
                </p>
              </div>
              {job.status === 'running' && (
                <Button size="sm" variant="ghost" onClick={() => cancelJob.mutate(job.id)}>
                  {t('common.cancel')}
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
