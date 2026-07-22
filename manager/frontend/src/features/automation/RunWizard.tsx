import { useEffect, useState } from 'react';
import { Play } from 'lucide-react';
import type { AutomationTemplate, StartRunPayload } from '@/types/api';
import { Modal } from '@/components/ui/Modal';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Checkbox } from '@/components/ui/Checkbox';
import { Button } from '@/components/ui/Button';
import { useProfiles } from '@/features/profiles/api';
import { useT } from '@/i18n';
import { useCredentialPool, useStartRun } from './api';

/** Configure a run for a template: pick profiles, parallelism, and where
 * credentials come from (pool vs per-profile variables). */
export function RunWizard({
  template,
  onClose,
  onStarted,
}: {
  template: AutomationTemplate | null;
  onClose: () => void;
  onStarted: (runId: string) => void;
}) {
  const t = useT();
  const profiles = useProfiles({ page: 1, page_size: 100, sort: 'name' });
  const pool = useCredentialPool();
  const startRun = useStartRun();

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [maxParallel, setMaxParallel] = useState(3);
  const [fromPool, setFromPool] = useState(true);
  const [vars, setVars] = useState<Record<string, Record<string, string>>>({});

  useEffect(() => {
    if (template) {
      setSelected(new Set());
      setMaxParallel(3);
      setFromPool(true);
      setVars({});
    }
  }, [template]);

  const items = profiles.data?.items ?? [];
  const variables = template?.variables ?? [];
  const hasVars = variables.length > 0;
  const poolAvailable = pool.data?.available ?? 0;

  const toggle = (id: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const setVar = (pid: string, key: string, value: string) =>
    setVars((current) => ({ ...current, [pid]: { ...(current[pid] ?? {}), [key]: value } }));

  const start = () => {
    if (!template || selected.size === 0) return;
    const assignments = [...selected].map((profile_id) => ({
      profile_id,
      variables: hasVars && !fromPool ? (vars[profile_id] ?? {}) : {},
      credential_id: hasVars && fromPool ? 'pool' : null,
    }));
    const payload: StartRunPayload = { assignments, max_parallel: maxParallel };
    startRun.mutate(
      { templateId: template.id, payload },
      {
        onSuccess: (run) => {
          onStarted(run.id);
          onClose();
        },
      },
    );
  };

  return (
    <Modal
      open={Boolean(template)}
      onClose={onClose}
      size="lg"
      title={t('auto.run.title', { name: template?.name ?? '' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            onClick={start}
            loading={startRun.isPending}
            disabled={selected.size === 0}
          >
            <Play className="h-3.5 w-3.5" /> {t('auto.run.start')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t('auto.run.profiles')} hint={t('auto.run.profilesHint')}>
          {items.length === 0 ? (
            <p className="text-2xs text-ink-faint">{t('auto.run.noProfiles')}</p>
          ) : (
            <div className="max-h-52 space-y-0.5 overflow-auto rounded-md border border-line p-1">
              {items.map((p) => (
                <label
                  key={p.id}
                  className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 hover:bg-surface-sunken"
                >
                  <Checkbox checked={selected.has(p.id)} onChange={() => toggle(p.id)} aria-label={p.name} />
                  <span className="text-[13px] text-ink">{p.name}</span>
                </label>
              ))}
            </div>
          )}
          {selected.size > 0 && (
            <p className="mt-1 text-2xs text-ink-faint">
              {t('auto.run.selected', { count: selected.size })}
            </p>
          )}
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label={t('auto.run.maxParallel')}>
            <Select
              value={String(maxParallel)}
              onChange={(e) => setMaxParallel(Number(e.target.value))}
              options={[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) }))}
            />
          </Field>
          {hasVars && (
            <Field label={t('auto.run.credential')}>
              <Select
                value={fromPool ? 'pool' : 'manual'}
                onChange={(e) => setFromPool(e.target.value === 'pool')}
                options={[
                  { value: 'pool', label: t('auto.run.credentialPool', { count: poolAvailable }) },
                  { value: 'manual', label: t('auto.run.credentialManual') },
                ]}
              />
            </Field>
          )}
        </div>

        {hasVars && !fromPool && selected.size > 0 && (
          <div className="overflow-x-auto rounded-md border border-line">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-2xs uppercase tracking-wide text-ink-faint">
                  <th className="px-2 py-2 text-left font-semibold">{t('auto.run.profiles')}</th>
                  {variables.map((v) => (
                    <th key={v} className="px-2 py-2 text-left font-semibold">
                      {v}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...selected].map((pid) => {
                  const profile = items.find((x) => x.id === pid);
                  return (
                    <tr key={pid} className="border-b border-line/60">
                      <td className="px-2 py-1.5 text-[13px] text-ink">{profile?.name ?? pid}</td>
                      {variables.map((v) => (
                        <td key={v} className="px-2 py-1.5">
                          <Input
                            type={v === 'password' ? 'password' : 'text'}
                            value={vars[pid]?.[v] ?? ''}
                            onChange={(e) => setVar(pid, v, e.target.value)}
                          />
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Modal>
  );
}
