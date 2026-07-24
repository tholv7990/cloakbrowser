import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import { useT } from '@/i18n';
import type { ArrangeLayout, ArrangeResult } from '@/types/api';
import { useMonitors, useArrangeWindows } from './api';

export function SynchronizePage() {
  const t = useT();
  const profilesQuery = useQuery({
    queryKey: queryKeys.profiles({ page: 1, page_size: 200 }),
    queryFn: () => api.listProfiles({ page: 1, page_size: 200 }),
  });
  const monitorsQuery = useMonitors();
  const arrange = useArrangeWindows();

  const running = useMemo(
    () => (profilesQuery.data?.items ?? []).filter((p) => p.runtime_state === 'running'),
    [profilesQuery.data],
  );

  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [monitorId, setMonitorId] = useState<string>('');
  const [layout, setLayout] = useState<ArrangeLayout>('grid');
  const [results, setResults] = useState<Record<string, ArrangeResult>>({});

  // Default: all running selected; primary monitor.
  useEffect(() => {
    setSelected((prev) => {
      const next = { ...prev };
      for (const p of running) if (!(p.id in next)) next[p.id] = true;
      return next;
    });
  }, [running]);
  useEffect(() => {
    const monitors = monitorsQuery.data ?? [];
    if (!monitorId && monitors.length) {
      setMonitorId((monitors.find((m) => m.is_primary) ?? monitors[0]).id);
    }
  }, [monitorsQuery.data, monitorId]);

  const chosenIds = running.filter((p) => selected[p.id]).map((p) => p.id);

  async function onTile() {
    if (!chosenIds.length) return;
    // The monitor list resolves async; fall back to the primary/first monitor
    // rather than silently no-opping a click that landed before it settled.
    const monitors = monitorsQuery.data ?? [];
    const targetMonitorId = monitorId || (monitors.find((m) => m.is_primary) ?? monitors[0])?.id;
    if (!targetMonitorId) return;
    const res = await arrange.mutateAsync({
      profile_ids: chosenIds,
      monitor_id: targetMonitorId,
      layout,
    });
    setResults(Object.fromEntries(res.results.map((r) => [r.profile_id, r])));
  }

  function resultLabel(id: string): string | null {
    const r = results[id];
    if (!r) return null;
    if (r.ok) return t('synchronize.ok');
    return r.error === 'not_running' ? t('synchronize.notRunning') : t('synchronize.failed');
  }

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <header>
        <h1 className="text-lg font-semibold text-ink">{t('synchronize.title')}</h1>
        <p className="text-sm text-ink-muted">{t('synchronize.subtitle')}</p>
      </header>

      <div className="grid flex-1 grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        {/* Running profiles */}
        <section className="rounded-lg border border-line bg-surface p-3">
          <h2 className="mb-2 text-[13px] font-medium text-ink-muted">
            {t('synchronize.running')}
          </h2>
          {running.length === 0 ? (
            <p className="p-4 text-sm text-ink-muted">{t('synchronize.noRunning')}</p>
          ) : (
            <ul className="space-y-1">
              {running.map((p) => (
                <li key={p.id} className="flex items-center justify-between rounded-md px-2 py-1.5">
                  <label className="flex items-center gap-2 text-sm text-ink">
                    <input
                      type="checkbox"
                      checked={!!selected[p.id]}
                      onChange={(e) =>
                        setSelected((s) => ({ ...s, [p.id]: e.target.checked }))
                      }
                    />
                    {p.name}
                  </label>
                  {resultLabel(p.id) && (
                    <span className="text-xs text-ink-muted">{resultLabel(p.id)}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Console */}
        <section className="space-y-4 rounded-lg border border-line bg-surface p-4">
          <div>
            <label className="mb-1 block text-[13px] font-medium text-ink">
              {t('synchronize.monitor')}
            </label>
            <select
              className="w-full rounded-md border border-line bg-surface-sunken px-2 py-1.5 text-sm"
              value={monitorId}
              onChange={(e) => setMonitorId(e.target.value)}
            >
              {(monitorsQuery.data ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>

          <fieldset>
            <legend className="mb-1 text-[13px] font-medium text-ink">
              {t('synchronize.layout')}
            </legend>
            {(['grid', 'cascade'] as ArrangeLayout[]).map((value) => (
              <label key={value} className="mr-4 inline-flex items-center gap-1.5 text-sm">
                <input
                  type="radio"
                  name="layout"
                  checked={layout === value}
                  onChange={() => setLayout(value)}
                />
                {t(`synchronize.${value}`)}
              </label>
            ))}
          </fieldset>

          <button
            type="button"
            onClick={onTile}
            disabled={!chosenIds.length || arrange.isPending}
            className="w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {t('synchronize.tile')}
          </button>
        </section>
      </div>
    </div>
  );
}

export default SynchronizePage;
