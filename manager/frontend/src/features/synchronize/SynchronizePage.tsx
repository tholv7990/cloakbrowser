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
  useBroadcast,
} from './api';
import { toNavigableUrl } from './urlOrSearch';

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
  const broadcast = useBroadcast();

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
  const [sendUrl, setSendUrl] = useState('');
  const [sendText, setSendText] = useState('');
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
  // Drop a control selection whose profile stopped, so Start can't be armed with a
  // profile that is no longer running.
  useEffect(() => {
    if (controlId && !running.some((p) => p.id === controlId)) setControlId('');
  }, [running, controlId]);

  const chosenIds = running.filter((p) => selected[p.id]).map((p) => p.id);
  // Followers are the selected profiles minus the control window itself.
  const followerIds = chosenIds.filter((id) => id !== controlId);
  // With nothing running there is nothing to sync, so never offer Stop — the
  // backend ends the session on its own once the synced windows are gone, and this
  // keeps the button from stranding on "Stop sync" until that status poll lands.
  const isSyncing = (syncStatus.data?.active ?? false) && running.length > 0;

  const canStart = !isSyncing && !!controlId && followerIds.length > 0;

  async function onStartSync() {
    if (!canStart) return;
    await startSync.mutateAsync({
      control_profile_id: controlId,
      follower_profile_ids: followerIds,
    });
  }

  async function onStopSync() {
    if (!isSyncing) return;
    await stopSync.mutateAsync();
  }

  async function onSend(payload: { url?: string; text?: string }) {
    if (!chosenIds.length) return;
    setResults({});
    const res = await broadcast.mutateAsync({ profile_ids: chosenIds, ...payload });
    setResults(Object.fromEntries(res.results.map((r) => [r.profile_id, r])));
  }

  /** What this profile is doing right now, in the user's terms — colour-coded so
   *  the control and its followers are distinguishable at a glance. */
  function statusPill(id: string) {
    const [label, tone] =
      isSyncing && id === controlId
        ? [t('sync.control'), 'bg-accent/15 text-accent']
        : isSyncing && followerIds.includes(id)
          ? [t('sync.following'), 'bg-success/15 text-success']
          : [t('sync.running'), 'bg-surface-sunken text-ink-muted'];
    return (
      <span className={`rounded-full px-2 py-0.5 text-2xs font-medium ${tone}`}>{label}</span>
    );
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
        <p className="text-sm text-ink-muted">{t('sync.desc')}</p>
      </header>

      {/* The primary actions sit at the top, both always visible, so it is obvious
          which one is available rather than one button changing meaning. */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onStartSync}
          disabled={!canStart || startSync.isPending}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
        >
          {t('sync.start')}
        </button>
        <button
          type="button"
          onClick={onStopSync}
          disabled={!isSyncing || stopSync.isPending}
          className="rounded-md bg-danger px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
        >
          {t('sync.stop')}
        </button>
        <span className="ml-1 text-xs text-ink-muted">
          {t('sync.selected', { count: chosenIds.length })}
        </span>
        {isSyncing && (
          <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs font-medium text-accent">
            {t('sync.activeCount', { count: followerIds.length })}
          </span>
        )}
        {startSync.isError && (
          <span className="text-xs text-danger">{t('sync.failed')}</span>
        )}
      </div>

      {/* One line that says what to do next, rather than leaving the order of
          Tile / control / Start to be discovered by trial. */}
      {running.length > 0 && (
        <p className="text-xs text-ink-faint">
          {isSyncing
            ? t('sync.stepSyncing')
            : !controlId
              ? t('sync.stepPickControl')
              : followerIds.length === 0
                ? t('sync.stepNeedFollower')
                : t('sync.stepReady')}
        </p>
      )}

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
            <div className="min-h-0 flex-1 overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-surface">
                  <tr className="border-b border-line text-left text-2xs uppercase tracking-wide text-ink-faint">
                    <th className="w-8 px-2 py-1.5">
                      <input
                        type="checkbox"
                        aria-label={t('sync.selectAll')}
                        checked={running.every((p) => selected[p.id])}
                        onChange={(e) =>
                          setSelected(
                            Object.fromEntries(running.map((p) => [p.id, e.target.checked])),
                          )
                        }
                      />
                    </th>
                    <th className="px-2 py-1.5 font-medium">{t('sync.colProfile')}</th>
                    <th className="px-2 py-1.5 font-medium">{t('sync.colStatus')}</th>
                    <th className="w-24 px-2 py-1.5 font-medium">{t('sync.control')}</th>
                  </tr>
                </thead>
                <tbody>
                  {running.map((p) => (
                    <tr key={p.id} className="border-b border-line/50 last:border-0">
                      <td className="px-2 py-2">
                        <input
                          type="checkbox"
                          aria-label={p.name}
                          checked={!!selected[p.id]}
                          onChange={(e) =>
                            setSelected((s) => ({ ...s, [p.id]: e.target.checked }))
                          }
                        />
                      </td>
                      <td className="max-w-0 truncate px-2 py-2 text-ink">{p.name}</td>
                      <td className="px-2 py-2 text-xs text-ink-muted">
                        {statusPill(p.id)}
                        {resultLabel(p.id) && (
                          <span className="ml-2 text-ink-faint">{resultLabel(p.id)}</span>
                        )}
                      </td>
                      <td className="px-2 py-2">
                        <input
                          type="radio"
                          name="sync-control"
                          aria-label={`${t('sync.control')}: ${p.name}`}
                          checked={controlId === p.id}
                          disabled={isSyncing}
                          onChange={() => setControlId(p.id)}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* Console: send-to-all first — it works without a sync session, so it is
            the thing most reachable at any moment. Window layout below it. */}
        <section className="min-h-0 space-y-5 overflow-y-auto rounded-lg border border-line bg-surface p-4">
          <div className="space-y-2">
            <h2 className="text-[13px] font-medium text-ink">{t('sync.sendTitle')}</h2>
            <p className="text-xs text-ink-muted">{t('sync.sendDesc')}</p>
            <input
              type="text"
              value={sendUrl}
              onChange={(e) => setSendUrl(e.target.value)}
              placeholder={t('sync.urlPlaceholder')}
              aria-label={t('sync.openUrl')}
              className="w-full rounded-md border border-line bg-surface-sunken px-2 py-1.5 text-sm"
              onKeyDown={(e) => {
                if (e.key === 'Enter') onSend({ url: toNavigableUrl(sendUrl) ?? undefined });
              }}
            />
            <button
              type="button"
              onClick={() => onSend({ url: toNavigableUrl(sendUrl) ?? undefined })}
              disabled={!chosenIds.length || !toNavigableUrl(sendUrl) || broadcast.isPending}
              className="w-full rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
            >
              {t('sync.openUrl')}
            </button>
            <textarea
              rows={2}
              value={sendText}
              onChange={(e) => setSendText(e.target.value)}
              placeholder={t('sync.textPlaceholder')}
              aria-label={t('sync.sendText')}
              className="w-full rounded-md border border-line bg-surface-sunken px-2 py-1.5 text-sm"
            />
            <button
              type="button"
              onClick={() => onSend({ text: sendText })}
              disabled={!chosenIds.length || !sendText || broadcast.isPending}
              className="w-full rounded-md border border-line px-3 py-1.5 text-sm font-medium text-ink disabled:opacity-40"
            >
              {t('sync.sendText')}
            </button>
            <p className="text-xs text-ink-faint">{t('sync.textHint')}</p>
          </div>

          <div className="space-y-3 border-t border-line pt-4">
            <h2 className="text-[13px] font-medium text-ink">{t('sync.layoutTitle')}</h2>
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
            <p className="text-xs text-ink-faint">{t('sync.tileHint')}</p>
          </div>
        </section>
      </div>
    </div>
  );
}

export default SynchronizePage;
