import type { SessionExitReason } from '@/types/api';
import { Badge, type Tone } from '@/components/ui/Badge';
import { LoadingBlock } from '@/components/ui/states';
import { formatDuration, relativeTime } from '@/lib/format';
import { useT, type TranslationKey } from '@/i18n';
import { useSessions } from './api';

const EXIT_TONE: Record<SessionExitReason, Tone> = {
  closed: 'neutral',
  stopped: 'neutral',
  crashed: 'danger',
  timeout: 'warning',
  unknown: 'neutral',
};

export function SessionHistory() {
  const t = useT();
  const sessions = useSessions();
  const rows = sessions.data ?? [];

  return (
    <section className="rounded-lg border border-line bg-surface p-4">
      <h2 className="font-display text-[15px] font-semibold text-ink">{t('sess.title')}</h2>
      <p className="mt-0.5 text-2xs text-ink-faint">{t('sess.subtitle')}</p>

      {sessions.isLoading ? (
        <LoadingBlock label="…" className="py-6" />
      ) : rows.length === 0 ? (
        <p className="mt-3 rounded-md border border-line bg-surface-sunken px-3 py-4 text-center text-2xs text-ink-faint">
          {t('sess.empty')}
        </p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-2xs uppercase tracking-wide text-ink-faint">
                <th className="px-2 py-2 text-left font-semibold">{t('sess.col.profile')}</th>
                <th className="px-2 py-2 text-left font-semibold">{t('sess.col.started')}</th>
                <th className="px-2 py-2 text-right font-semibold">{t('sess.col.duration')}</th>
                <th className="px-2 py-2 text-right font-semibold">{t('sess.col.startup')}</th>
                <th className="px-2 py-2 text-left font-semibold">{t('sess.col.exit')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((session) => (
                <tr key={session.id} className="border-b border-line/60">
                  <td className="max-w-[200px] truncate px-2 py-2 text-[13px] text-ink">
                    {session.profile_name}
                  </td>
                  <td className="px-2 py-2 text-2xs text-ink-muted">
                    {relativeTime(session.started_at)}
                  </td>
                  <td className="px-2 py-2 text-right text-[13px] tabular-nums text-ink-muted">
                    {session.duration_seconds != null
                      ? formatDuration(session.duration_seconds)
                      : t('sess.ongoing')}
                  </td>
                  <td className="px-2 py-2 text-right text-[13px] tabular-nums text-ink-faint">
                    {session.startup_ms != null ? `${session.startup_ms} ms` : '—'}
                  </td>
                  <td className="px-2 py-2">
                    {session.exit_reason ? (
                      <Badge tone={EXIT_TONE[session.exit_reason]}>
                        {t(`sess.exit.${session.exit_reason}` as TranslationKey)}
                      </Badge>
                    ) : (
                      <span className="text-ink-faint">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
