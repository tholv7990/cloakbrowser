import { useEffect, useState } from 'react';
import { Activity, AlertTriangle, Ban, Download, ExternalLink, Play } from 'lucide-react';
import { useProfiles } from '@/features/profiles/api';
import { Badge, type Tone } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/states';
import { absoluteApiResource } from '@/api/config';
import { relativeTime } from '@/lib/format';
import { useT, type TranslationKey } from '@/i18n';
import type { DiagnosticKind, DiagnosticStatus } from '@/types/api';
import { useCancelDiagnostic, useDiagnostics, useRunDiagnostic } from './api';

const KINDS: DiagnosticKind[] = ['pixelscan', 'iphey', 'cloudflare', 'google_search'];

const STATUS_TONE: Record<DiagnosticStatus, Tone> = {
  queued: 'neutral',
  running: 'info',
  passed: 'success',
  warning: 'warning',
  failed: 'danger',
  cancelled: 'neutral',
};

const MAX_VISIBLE_FINDINGS = 12;

function findingLabel(key: string): string {
  const words = key
    .split('_')
    .filter(Boolean)
    .map((part) => part.toLowerCase())
    .join(' ');
  return words ? words[0].toUpperCase() + words.slice(1) : key;
}

function findingValue(value: boolean | string, yes: string, no: string): string {
  if (typeof value === 'boolean') return value ? yes : no;
  return findingLabel(value);
}

export function DiagnosticsPage() {
  const t = useT();
  const [profileCatalogSearch, setProfileCatalogSearch] = useState('');
  const [profileCatalogPage, setProfileCatalogPage] = useState(1);
  const profiles = useProfiles({
    page: profileCatalogPage,
    page_size: 50,
    sort: 'name',
    query: profileCatalogSearch || undefined,
  });
  const [profileId, setProfileId] = useState('');
  const [kind, setKind] = useState<Exclude<DiagnosticKind, 'direct_google_control'>>('pixelscan');
  const [statusFilter, setStatusFilter] = useState<DiagnosticStatus | ''>('');
  const [kindFilter, setKindFilter] = useState<DiagnosticKind | ''>('');
  const [profileFilter, setProfileFilter] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const diagnostics = useDiagnostics({
    profile: profileFilter || undefined,
    status: statusFilter || undefined,
    kind: kindFilter || undefined,
    page,
    page_size: pageSize,
  });
  const run = useRunDiagnostic();
  const cancel = useCancelDiagnostic();
  const runs = diagnostics.data?.items ?? [];
  const profileOptions = new Map(
    (profiles.data?.items ?? []).map((profile) => [profile.id, profile.name]),
  );
  for (const run of runs) {
    if (run.profile_id && !profileOptions.has(run.profile_id)) {
      profileOptions.set(run.profile_id, run.profile_id);
    }
  }
  if (profileId && !profileOptions.has(profileId)) profileOptions.set(profileId, profileId);
  if (profileFilter && !profileOptions.has(profileFilter)) {
    profileOptions.set(profileFilter, profileFilter);
  }

  useEffect(() => setPage(1), [profileFilter, statusFilter, kindFilter, pageSize]);
  useEffect(() => setProfileCatalogPage(1), [profileCatalogSearch]);

  return (
    // The app shell's <main> is overflow-hidden, so each page owns its scroll.
    <div className="h-full overflow-y-auto">
    <div className="mx-auto max-w-5xl space-y-5 px-5 py-6">
      <section className="rounded-lg border border-line bg-surface p-4">
        <h2 className="font-display text-[15px] font-semibold text-ink">{t('diag.controls')}</h2>
        <p className="mt-1 text-[13px] text-ink-muted">{t('diag.observationOnly')}</p>
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface-sunken p-2">
          <Input
            type="search"
            aria-label={t('diag.profileSearch')}
            value={profileCatalogSearch}
            onChange={(event) => setProfileCatalogSearch(event.target.value)}
            placeholder={t('diag.profileSearchPlaceholder')}
            className="min-w-56 flex-1"
          />
          <span className="text-2xs text-ink-muted">
            {t('diag.profilePage', {
              page: profiles.data?.page ?? profileCatalogPage,
              pages: profiles.data?.pages ?? 1,
            })}
          </span>
          <Button
            size="sm"
            variant="ghost"
            aria-label={t('diag.profilePreviousPage')}
            disabled={profileCatalogPage <= 1 || profiles.isFetching}
            onClick={() => setProfileCatalogPage((current) => Math.max(1, current - 1))}
          >
            {t('common.previous')}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label={t('diag.profileNextPage')}
            disabled={
              profiles.isFetching || !profiles.data || profileCatalogPage >= profiles.data.pages
            }
            onClick={() => setProfileCatalogPage((current) => current + 1)}
          >
            {t('common.next')}
          </Button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            onClick={() => run.mutate({ kind: 'direct_google_control', profileId: null })}
            loading={run.isPending}
          >
            <Play className="h-3.5 w-3.5" /> {t('diag.runGoogleControl')}
          </Button>
          <Select
            aria-label={t('diag.target')}
            value={kind}
            onChange={(event) => setKind(event.target.value as typeof kind)}
            options={KINDS.map((item) => ({
              value: item,
              label: t(`diag.kind.${item}` as TranslationKey),
            }))}
          />
          <Select
            aria-label={t('diag.profile')}
            value={profileId}
            onChange={(event) => setProfileId(event.target.value)}
            placeholder={t('diag.chooseProfile')}
            options={Array.from(profileOptions, ([value, label]) => ({ value, label }))}
          />
          <Button
            variant="primary"
            disabled={!profileId}
            loading={run.isPending}
            onClick={() => run.mutate({ kind, profileId })}
          >
            <Activity className="h-3.5 w-3.5" /> {t('diag.runSelected')}
          </Button>
        </div>
        {run.isError && <p className="mt-2 text-2xs text-danger">{(run.error as Error).message}</p>}
        <p className="mt-3 flex items-start gap-2 text-2xs text-ink-faint">
          <Ban className="h-3.5 w-3.5 shrink-0" /> {t('diag.noCaptcha')}
        </p>
      </section>

      <section>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-display text-[15px] font-semibold text-ink">{t('diag.history')}</h2>
          <div className="flex flex-wrap gap-2">
            <Select
              aria-label={t('diag.filterProfile')}
              value={profileFilter}
              onChange={(event) => setProfileFilter(event.target.value)}
              options={[
                { value: '', label: t('diag.allProfiles') },
                ...Array.from(profileOptions, ([value, label]) => ({ value, label })),
              ]}
            />
            <Select
              aria-label={t('diag.filterKind')}
              value={kindFilter}
              onChange={(event) => setKindFilter(event.target.value as DiagnosticKind | '')}
              options={[
                { value: '', label: t('diag.allKinds') },
                { value: 'direct_google_control', label: t('diag.kind.direct_google_control') },
                ...KINDS.map((item) => ({
                  value: item,
                  label: t(`diag.kind.${item}` as TranslationKey),
                })),
              ]}
            />
            <Select
              aria-label={t('diag.filterStatus')}
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as DiagnosticStatus | '')}
              options={[
                { value: '', label: t('diag.allStatuses') },
                ...(['queued', 'running', 'passed', 'warning', 'failed', 'cancelled'] as const).map(
                  (status) => ({
                    value: status,
                    label: t(`diag.state.${status}` as TranslationKey),
                  }),
                ),
              ]}
            />
          </div>
        </div>

        {diagnostics.isLoading ? (
          <LoadingBlock label={t('diag.loadingRuns')} />
        ) : diagnostics.isError ? (
          <ErrorState
            message={(diagnostics.error as Error).message}
            onRetry={() => diagnostics.refetch()}
          />
        ) : runs.length === 0 ? (
          <EmptyState title={t('diag.empty.title')} description={t('diag.empty.desc')} />
        ) : (
          <ul className="space-y-2">
            {runs.map((item) => {
              const active = item.status === 'queued' || item.status === 'running';
              const captcha = item.error_code === 'captcha_user_action_required';
              return (
                <li key={item.id} className="rounded-lg border border-line bg-surface p-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone="neutral">
                          {t(`diag.kind.${item.kind}` as TranslationKey)}
                        </Badge>
                        <Badge tone={STATUS_TONE[item.status]}>
                          {t(`diag.state.${item.status}` as TranslationKey)}
                        </Badge>
                        <span className="text-2xs text-ink-faint">
                          {item.profile_id ? t('diag.profileRun') : t('diag.directRun')}
                        </span>
                      </div>
                      <p className="mt-2 text-[13px] text-ink-muted">
                        {item.summary ?? item.error_message}
                      </p>
                      {captcha && (
                        <p className="mt-2 flex items-center gap-2 text-[13px] text-warning">
                          <AlertTriangle className="h-4 w-4" /> {t('diag.captchaAction')}
                        </p>
                      )}
                      {Object.keys(item.findings).length > 0 && (
                        <dl className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2">
                          {Object.entries(item.findings)
                            .slice(0, MAX_VISIBLE_FINDINGS)
                            .map(([key, value]) => (
                              <div
                                key={key}
                                className="flex items-center justify-between gap-3 rounded bg-surface-sunken px-2 py-1 text-2xs"
                              >
                                <dt className="text-ink-faint">{findingLabel(key)}</dt>
                                <dd className="font-medium text-ink">
                                  {findingValue(value, t('common.yes'), t('common.no'))}
                                </dd>
                              </div>
                            ))}
                        </dl>
                      )}
                      {active && (
                        <div
                          className="mt-2"
                          role="progressbar"
                          aria-label={t('diag.progress', { progress: item.progress })}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-valuenow={item.progress}
                        >
                          <div className="h-1.5 overflow-hidden rounded bg-surface-sunken">
                            <div
                              className="h-full bg-accent"
                              style={{ width: `${item.progress}%` }}
                            />
                          </div>
                          <span className="text-2xs text-ink-faint">{item.progress}%</span>
                        </div>
                      )}
                      {(item.report_url || item.screenshot_url) && (
                        <div className="mt-2 flex flex-wrap gap-2">
                          {item.report_url && (
                            <a
                              href={absoluteApiResource(item.report_url)}
                              className="inline-flex items-center gap-1 text-2xs font-medium text-accent hover:underline"
                              download
                            >
                              <Download className="h-3 w-3" /> {t('diag.downloadReport')}
                            </a>
                          )}
                          {item.screenshot_url && (
                            <a
                              href={absoluteApiResource(item.screenshot_url)}
                              className="inline-flex items-center gap-1 text-2xs font-medium text-accent hover:underline"
                              target="_blank"
                              rel="noreferrer"
                            >
                              <ExternalLink className="h-3 w-3" /> {t('diag.openScreenshot')}
                            </a>
                          )}
                        </div>
                      )}
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-2">
                      <span className="text-2xs text-ink-faint">
                        {t('diag.observed', {
                          time: relativeTime(item.completed_at ?? item.requested_at),
                        })}
                      </span>
                      {active && (
                        <Button
                          variant="ghost"
                          size="sm"
                          loading={cancel.isPending}
                          onClick={() => cancel.mutate(item.id)}
                        >
                          {t('common.cancel')}
                        </Button>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {diagnostics.data && diagnostics.data.total > 0 && (
          <div className="mt-3 flex flex-wrap items-center justify-end gap-2 text-2xs text-ink-muted">
            <Select
              aria-label={t('diag.pageSize')}
              value={String(pageSize)}
              onChange={(event) => setPageSize(Number(event.target.value))}
              options={[20, 50, 100].map((size) => ({ value: String(size), label: String(size) }))}
            />
            <span>
              {t('diag.page', { page: diagnostics.data.page, pages: diagnostics.data.pages })}
            </span>
            <Button
              size="sm"
              variant="ghost"
              aria-label={t('diag.previousPage')}
              disabled={page <= 1}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              {t('common.previous')}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={t('diag.nextPage')}
              disabled={page >= diagnostics.data.pages}
              onClick={() => setPage((current) => current + 1)}
            >
              {t('common.next')}
            </Button>
          </div>
        )}
      </section>
    </div>
    </div>
  );
}
