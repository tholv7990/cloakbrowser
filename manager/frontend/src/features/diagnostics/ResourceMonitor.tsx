import { Activity, Cpu, Globe2, Server } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { RuntimeBadge } from '@/components/domain/StatusBadges';
import { LoadingBlock, ErrorState } from '@/components/ui/states';
import { formatBytes } from '@/lib/format';
import { useT } from '@/i18n';
import { useResources } from './api';

function pct(value: number): string {
  return `${Math.max(0, Math.min(100, value)).toFixed(0)}%`;
}

function Meter({
  icon: Icon,
  label,
  value,
  detail,
  percent,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  detail: string;
  percent: number;
}) {
  return (
    <article className="rounded-md border border-line bg-surface-sunken p-3">
      <div className="flex items-center gap-1.5 text-ink-muted">
        <Icon className="h-3.5 w-3.5" />
        <span className="text-2xs font-medium uppercase tracking-wide">{label}</span>
      </div>
      <p className="mt-1 font-display text-lg font-semibold text-ink">{value}</p>
      <p className="truncate text-2xs text-ink-faint">{detail}</p>
      <div className="mt-2 h-1 overflow-hidden rounded-full bg-line">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-500"
          style={{ width: pct(percent) }}
        />
      </div>
    </article>
  );
}

export function ResourceMonitor() {
  const t = useT();
  const resources = useResources();

  return (
    <section className="rounded-lg border border-line bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-1.5 text-accent">
            <Cpu className="h-3.5 w-3.5" />
            <span className="text-2xs font-semibold uppercase tracking-wide">
              {t('res.kicker')}
            </span>
          </div>
          <h2 className="font-display text-[15px] font-semibold text-ink">{t('res.title')}</h2>
          <p className="mt-0.5 text-2xs text-ink-faint">{t('res.subtitle')}</p>
        </div>
        {resources.isFetching && !resources.isLoading && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-success/40 bg-success/10 px-2 py-0.5 text-2xs text-success">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-success" />
            {t('res.live')}
          </span>
        )}
      </div>

      {resources.isLoading ? (
        <LoadingBlock label={t('res.loading')} className="py-6" />
      ) : resources.isError ? (
        <ErrorState message={t('res.error')} onRetry={() => resources.refetch()} />
      ) : resources.data ? (
        <>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <Meter
              icon={Activity}
              label={t('res.systemCpu')}
              value={`${resources.data.system.cpu_percent.toFixed(1)}%`}
              detail={t('res.logicalCpus', { count: resources.data.system.logical_cpus })}
              percent={resources.data.system.cpu_percent}
            />
            <Meter
              icon={Cpu}
              label={t('res.systemMemory')}
              value={`${resources.data.system.memory_percent.toFixed(1)}%`}
              detail={`${formatBytes(resources.data.system.memory_used_bytes)} / ${formatBytes(resources.data.system.memory_total_bytes)}`}
              percent={resources.data.system.memory_percent}
            />
            <Meter
              icon={Server}
              label={t('res.backend')}
              value={`${resources.data.backend.cpu_percent.toFixed(1)}%`}
              detail={formatBytes(resources.data.backend.memory_bytes)}
              percent={resources.data.backend.cpu_percent}
            />
            <Meter
              icon={Globe2}
              label={t('res.browsers')}
              value={`${resources.data.browsers.cpu_percent.toFixed(1)}%`}
              detail={`${formatBytes(resources.data.browsers.memory_bytes)} · ${t('res.profilesRunning', { count: resources.data.browsers.profiles_running })}`}
              percent={resources.data.browsers.cpu_percent}
            />
          </div>

          {resources.data.profiles.length === 0 ? (
            <p className="mt-3 rounded-md border border-line bg-surface-sunken px-3 py-4 text-center text-2xs text-ink-faint">
              {t('res.empty')}
            </p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-line text-2xs uppercase tracking-wide text-ink-faint">
                    <th scope="col" className="px-2 py-2 text-left font-semibold">
                      {t('res.col.profile')}
                    </th>
                    <th scope="col" className="px-2 py-2 text-left font-semibold">
                      {t('res.col.state')}
                    </th>
                    <th scope="col" className="px-2 py-2 text-right font-semibold">
                      {t('res.col.cpu')}
                    </th>
                    <th scope="col" className="px-2 py-2 text-right font-semibold">
                      {t('res.col.memory')}
                    </th>
                    <th scope="col" className="px-2 py-2 text-right font-semibold">
                      {t('res.col.processes')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {resources.data.profiles.map((row) => (
                    <tr
                      key={row.profile_id}
                      className="border-b border-line/60 hover:bg-surface-sunken/50"
                    >
                      <td className="max-w-[220px] truncate px-2 py-2 text-[13px] font-medium text-ink">
                        {row.profile_name}
                      </td>
                      <td className="px-2 py-2">
                        <RuntimeBadge state={row.runtime_state} />
                      </td>
                      <td className="px-2 py-2 text-right text-[13px] tabular-nums text-ink">
                        {row.cpu_percent.toFixed(1)}%
                      </td>
                      <td className="px-2 py-2 text-right text-[13px] tabular-nums text-ink-muted">
                        {formatBytes(row.memory_bytes)}
                      </td>
                      <td className="px-2 py-2 text-right text-[13px] tabular-nums text-ink-faint">
                        {row.process_count}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
