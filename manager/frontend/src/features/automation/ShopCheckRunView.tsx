import { useState } from 'react';
import { ArrowLeft, Download, Square, Trash2 } from 'lucide-react';
import type {
  ShopCheckEmailRead,
  ShopCheckEmailResult,
  ShopCheckRunStatus,
} from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Badge, type Tone } from '@/components/ui/Badge';
import { Select } from '@/components/ui/Select';
import { LoadingBlock, ErrorState } from '@/components/ui/states';
import { relativeTime } from '@/lib/format';
import { useT, type TranslationKey } from '@/i18n';
import {
  useCancelShopCheckRun,
  useExportShopCheckRun,
  useShopCheckEmails,
  useShopCheckRun,
} from './api';
import { ShopCheckCleanupDialog } from './ShopCheckCleanupDialog';

const ACTIVE: ShopCheckRunStatus[] = ['queued', 'preparing', 'running'];
const RESULTS: ShopCheckEmailResult[] = [
  'phone_otp_required',
  'email_otp_required',
  'login_success',
  'account_not_found',
  'email_rejected',
  'captcha_or_challenge',
  'proxy_failed',
  'navigation_failed',
  'unknown',
  'cancelled',
];
const RESULT_TONE: Record<ShopCheckEmailResult, Tone> = {
  phone_otp_required: 'success',
  email_otp_required: 'info',
  login_success: 'info',
  account_not_found: 'neutral',
  email_rejected: 'neutral',
  captcha_or_challenge: 'warning',
  proxy_failed: 'warning',
  navigation_failed: 'warning',
  unknown: 'warning',
  cancelled: 'neutral',
};
const STATUS_TONE: Record<ShopCheckRunStatus, Tone> = {
  queued: 'neutral',
  preparing: 'info',
  running: 'info',
  completed: 'success',
  completed_with_issues: 'warning',
  cancelled: 'neutral',
  failed: 'danger',
};

const resultLabel = (t: ReturnType<typeof useT>, result: ShopCheckEmailResult) =>
  t(`shopchk.result.${result}` as TranslationKey);

export function ShopCheckRunView({ runId, onBack }: { runId: string; onBack: () => void }) {
  const t = useT();
  const run = useShopCheckRun(runId);
  const cancel = useCancelShopCheckRun();
  const exportRun = useExportShopCheckRun();
  const [filter, setFilter] = useState<ShopCheckEmailResult | ''>('');
  const [page, setPage] = useState(1);
  const [cleanupOpen, setCleanupOpen] = useState(false);
  const emails = useShopCheckEmails(runId, { page, result: filter || null });

  if (run.isLoading) return <LoadingBlock label={t('shopchk.run.loading')} />;
  if (run.isError || !run.data)
    return <ErrorState message={(run.error as Error)?.message ?? 'Error'} onRetry={() => run.refetch()} />;

  const data = run.data;
  const isActive = ACTIVE.includes(data.status);
  const isFinished = !isActive;
  const ownedCount = data.workers.filter((w) => w.profile_id).length;
  const rows = emails.data?.items ?? [];
  const pages = emails.data?.pages ?? 1;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-1 text-2xs text-ink-muted hover:text-ink"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> {t('shopchk.run.back')}
        </button>
        <div className="flex items-center gap-1.5">
          {isActive && (
            <Button size="sm" variant="danger" onClick={() => cancel.mutate(runId)} loading={cancel.isPending}>
              <Square className="h-3.5 w-3.5" /> {t('shopchk.run.cancel')}
            </Button>
          )}
          {isFinished && (
            <Button size="sm" variant="secondary" onClick={() => exportRun.mutate(runId)} loading={exportRun.isPending}>
              <Download className="h-3.5 w-3.5" /> {t('shopchk.run.export')}
            </Button>
          )}
          {isFinished && ownedCount > 0 && data.cleanup_state !== 'done' && (
            <Button size="sm" variant="ghost" onClick={() => setCleanupOpen(true)}>
              <Trash2 className="h-3.5 w-3.5" /> {t('shopchk.run.cleanup')}
            </Button>
          )}
        </div>
      </div>

      {/* Header: status + progress. */}
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface p-3">
        <Badge tone={STATUS_TONE[data.status]}>{t(`shopchk.status.${data.status}` as TranslationKey)}</Badge>
        <span className="text-2xs text-ink-muted">
          {t('shopchk.run.progress', { done: data.terminal_count, total: data.total_emails })}
        </span>
        <span className="text-2xs text-ink-faint">
          {t('shopchk.run.grouping', { per: data.emails_per_profile, workers: data.worker_count })}
        </span>
        {data.region && <span className="text-2xs text-ink-faint">{data.region}</span>}
        <span className="ml-auto text-2xs text-ink-faint">{relativeTime(data.created_at)}</span>
      </div>

      {/* Persistent completion banner. */}
      {isFinished && (
        <div className="rounded-md border border-line bg-surface-sunken px-3 py-2 text-2xs text-ink-muted">
          {t('shopchk.run.doneBanner', {
            matched: data.result_counts.phone_otp_required ?? 0,
            total: data.total_emails,
          })}
          {data.cleanup_state === 'done' && ` · ${t('shopchk.run.cleaned')}`}
        </div>
      )}

      {/* Aggregate outcomes. */}
      {Object.keys(data.result_counts).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {RESULTS.filter((r) => data.result_counts[r]).map((r) => (
            <Badge key={r} tone={RESULT_TONE[r]}>
              {resultLabel(t, r)} · {data.result_counts[r]}
            </Badge>
          ))}
        </div>
      )}

      {/* Emails: filter + table. */}
      <div className="flex items-center gap-2">
        <span className="text-2xs text-ink-faint">{t('shopchk.run.filter')}</span>
        <Select
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value as ShopCheckEmailResult | '');
            setPage(1);
          }}
          className="h-8 w-56"
          options={[
            { value: '', label: t('shopchk.run.filterAll') },
            ...RESULTS.map((r) => ({ value: r, label: resultLabel(t, r) })),
          ]}
        />
      </div>

      <div className="divide-y divide-line rounded-md border border-line">
        {rows.length === 0 ? (
          <p className="px-3 py-6 text-center text-2xs text-ink-faint">{t('shopchk.run.noEmails')}</p>
        ) : (
          rows.map((email) => <EmailRow key={email.id} email={email} t={t} />)
        )}
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-between text-2xs text-ink-muted">
          <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            {t('common.previous')}
          </Button>
          <span>{t('shopchk.run.pageOf', { page, pages })}</span>
          <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
            {t('common.next')}
          </Button>
        </div>
      )}

      {run.data && (
        <ShopCheckCleanupDialog run={run.data} open={cleanupOpen} onClose={() => setCleanupOpen(false)} />
      )}
    </div>
  );
}

function EmailRow({
  email,
  t,
}: {
  email: ShopCheckEmailRead;
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string;
}) {
  const phone =
    email.result === 'phone_otp_required' && email.phone_prefix
      ? `${email.phone_prefix} ••${email.phone_suffix ?? ''}` +
        (email.phone_country_name ? ` · ${email.phone_country_name}` : '')
      : null;
  return (
    <div className="flex items-center gap-3 px-3 py-2">
      <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-ink">{email.email_masked}</span>
      {phone && (
        <span className="shrink-0 text-2xs text-ink-faint">
          {phone}
          {email.phone_confidence === 'ambiguous' && ` (${t('shopchk.phone.ambiguous')})`}
        </span>
      )}
      {email.result ? (
        <Badge tone={RESULT_TONE[email.result]}>{t(`shopchk.result.${email.result}` as TranslationKey)}</Badge>
      ) : (
        <Badge tone="neutral">{t(`shopchk.emailState.${email.state}` as TranslationKey)}</Badge>
      )}
    </div>
  );
}
