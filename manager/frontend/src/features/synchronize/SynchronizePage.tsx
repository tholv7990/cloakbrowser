import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import { useT } from '@/i18n';
import type { ArrangeLayout, ArrangeResult } from '@/types/api';
import {
  useMonitors,
  useArrangeWindows,
  useSyncStatus,
  useStartInputSync,
  useStopInputSync,
} from './api';

export function SynchronizePage() {
  const t = useT();
  const profilesQuery = useQuery({
    // page_size is capped at 100 by the backend (a bigger value 422s and the list
    // comes back empty) — 100 is plenty of profiles to tile.
    queryKey: queryKeys.profiles({ page: 1, page_size: 100 }),
    queryFn: () => api.listProfiles({ page: 1, page_size: 100 }),
    // Keep the list current as profiles start/stop while this page is open.
    refetchInterval: 3000,
  });
  const monitorsQuery = useMonitors();
  const arrange = useArrangeWindows();
  const syncStatus = useSyncStatus();
  const startSync = useStartInputSync();
  const stopSync = useStopInputSync();

  // A launched profile that the manager reconnected to after a restart is
  // 'detached' (still a live, tileable window), not 'running' — include both so
  // the list matches the "running" count in the header.
  const running = useMemo(
    () =>
      (profilesQuery.data?.items ?? []).filter(
        (p) => p.runtime_state === 'running' || p.runtime_state === 'detached',
      ),
    [profilesQuery.data],
  );

  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [controlId, setControlId] = useState<string>('');
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
  // Followers are the selected profiles minus the control window itself.
  const followerIds = chosenIds.filter((id) => id !== controlId);
  const isSyncing = syncStatus.data?.active ?? false;

  async function onToggleSync() {
    if (isSyncing) {
      await stopSync.mutateAsync();
      return;
    }
    if (!controlId || !followerIds.length) return;
    await startSync.mutateAsync({
      control_profile_id: controlId,
      follower_profile_ids: followerIds,
    });
  }

  async function onTile() {
    if (!chosenIds.length) return;
    // The monitor list resolves async; fall back to the primary/first monitor
    // rather than silently no-opping a click that landed before it settled.
    // (The Tile button is also disabled until a monitor is available, so this
    // is defense-in-depth rather than the only guard.)
    const monitors = monitorsQuery.data ?? [];
    const targetMonitorId = monitorId || (monitors.find((m) => m.is_primary) ?? monitors[0])?.id;
    if (!targetMonitorId) return;
    setResults({});
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

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        {/* Running profiles */}
        <section className="flex min-h-0 flex-col rounded-lg border border-line bg-surface p-3">
          <h2 className="mb-2 text-[13px] font-medium text-ink-muted">
            {t('synchronize.running')}
          </h2>
          {profilesQuery.isPending ? (
            <p className="p-4 text-sm text-ink-muted">{t('synchronize.loading')}</p>
          ) : running.length === 0 ? (
            <p className="p-4 text-sm text-ink-muted">{t('synchronize.noRunning')}</p>
          ) : (
            <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto">
              {running.map((p) => (
                <li key={p.id} className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5">
                  <label className="flex min-w-0 items-center gap-2 text-sm text-ink">
                    <input
                      type="checkbox"
                      checked={!!selected[p.id]}
                      onChange={(e) =>
                        setSelected((s) => ({ ...s, [p.id]: e.target.checked }))
                      }
                    />
                    <span className="truncate">{p.name}</span>
                  </label>
                  <div className="flex shrink-0 items-center gap-3">
                    {resultLabel(p.id) && (
                      <span className="text-xs text-ink-muted">{resultLabel(p.id)}</span>
                    )}
                    {/* Which window you drive; the rest follow it. */}
                    <label className="flex items-center gap-1 text-xs text-ink-muted">
                      <input
                        type="radio"
                        name="sync-control"
                        checked={controlId === p.id}
                        disabled={isSyncing}
                        onChange={() => setControlId(p.id)}
                      />
                      {t('sync.control')}
                    </label>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Console */}
        <section className="min-h-0 space-y-4 overflow-y-auto rounded-lg border border-line bg-surface p-4">
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
            disabled={
              !chosenIds.length ||
              arrange.isPending ||
              !(monitorsQuery.data && monitorsQuery.data.length)
            }
            className="w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {t('synchronize.tile')}
          </button>

          {/* Input sync: drive the control window, mirror to the followers. */}
          <div className="space-y-2 border-t border-line pt-4">
            <h2 className="text-[13px] font-medium text-ink">{t('sync.title')}</h2>
            <p className="text-xs text-ink-muted">{t('sync.desc')}</p>
            {isSyncing ? (
              <p className="text-xs text-ink">
                {t('sync.activeCount', {
                  count: syncStatus.data?.follower_profile_ids.length ?? 0,
                })}
              </p>
            ) : (
              <p className="text-xs text-ink-faint">{t('sync.tileHint')}</p>
            )}
            <button
              type="button"
              onClick={onToggleSync}
              disabled={
                startSync.isPending ||
                stopSync.isPending ||
                (!isSyncing && (!controlId || !followerIds.length))
              }
              className={`w-full rounded-md px-3 py-2 text-sm font-medium text-white disabled:opacity-50 ${
                isSyncing ? 'bg-danger' : 'bg-accent'
              }`}
            >
              {t(isSyncing ? 'sync.stop' : 'sync.start')}
            </button>
            {startSync.isError && (
              <p className="text-xs text-danger">{t('sync.failed')}</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

export default SynchronizePage;
