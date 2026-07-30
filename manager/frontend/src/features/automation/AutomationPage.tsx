import { useState } from 'react';
import { Play, Plus, ShieldCheck, Trash2 } from 'lucide-react';
import type { AutomationTemplate } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { IconButton } from '@/components/ui/IconButton';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/states';
import { relativeTime } from '@/lib/format';
import { cn } from '@/lib/cn';
import { useT, type TranslationKey } from '@/i18n';
import { useDeleteTemplate, useShopCheckRuns, useTemplates } from './api';
import { RecordDialog } from './RecordDialog';
import { RunWizard } from './RunWizard';
import { RunView } from './RunView';
import { CredentialsPanel } from './CredentialsPanel';
import { ShopCheckWizard } from './ShopCheckWizard';
import { ShopCheckRunView } from './ShopCheckRunView';

type Tab = 'templates' | 'runs' | 'shop-check' | 'credentials';
const TABS: { id: Tab; key: TranslationKey }[] = [
  { id: 'templates', key: 'auto.tab.templates' },
  { id: 'runs', key: 'auto.tab.runs' },
  { id: 'shop-check', key: 'auto.tab.shopCheck' },
  { id: 'credentials', key: 'auto.tab.credentials' },
];

export function AutomationPage() {
  const t = useT();
  const [tab, setTab] = useState<Tab>('templates');
  const [recordOpen, setRecordOpen] = useState(false);
  const [runTemplate, setRunTemplate] = useState<AutomationTemplate | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AutomationTemplate | null>(null);
  const [shopWizardOpen, setShopWizardOpen] = useState(false);
  const [activeShopRunId, setActiveShopRunId] = useState<string | null>(null);

  const templates = useTemplates();
  const deleteTemplate = useDeleteTemplate();
  const list = templates.data ?? [];
  const shopRuns = useShopCheckRuns();

  return (
    // The app shell's <main> is overflow-hidden, so each page owns its scroll.
    <div className="h-full overflow-y-auto">
    <div className="mx-auto max-w-5xl px-5 py-6">
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className="text-[13px] text-ink-muted">{t('auto.subtitle')}</p>
        <Button variant="primary" size="sm" onClick={() => setRecordOpen(true)}>
          <Plus className="h-3.5 w-3.5" /> {t('auto.record')}
        </Button>
      </div>

      <div className="mb-4 flex gap-1 border-b border-line">
        {TABS.map((tabDef) => (
          <button
            key={tabDef.id}
            type="button"
            onClick={() => setTab(tabDef.id)}
            className={cn(
              '-mb-px border-b-2 px-3 py-2 text-[13px] font-medium transition-colors',
              tab === tabDef.id
                ? 'border-accent text-ink'
                : 'border-transparent text-ink-muted hover:text-ink',
            )}
          >
            {t(tabDef.key)}
          </button>
        ))}
      </div>

      {tab === 'templates' &&
        (templates.isLoading ? (
          <LoadingBlock label={t('auto.templates.loading')} />
        ) : templates.isError ? (
          <ErrorState
            message={(templates.error as Error).message}
            onRetry={() => templates.refetch()}
          />
        ) : list.length === 0 ? (
          <EmptyState
            icon={<Play className="h-5 w-5" />}
            title={t('auto.templates.empty.title')}
            description={t('auto.templates.empty.desc')}
            action={
              <Button variant="primary" size="sm" onClick={() => setRecordOpen(true)}>
                <Plus className="h-3.5 w-3.5" /> {t('auto.record')}
              </Button>
            }
          />
        ) : (
          <div className="space-y-2">
            {list.map((tpl) => (
              <div
                key={tpl.id}
                className="flex items-center gap-3 rounded-lg border border-line bg-surface p-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-ink">{tpl.name}</p>
                  {tpl.description && (
                    <p className="truncate text-2xs text-ink-faint">{tpl.description}</p>
                  )}
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-2xs text-ink-muted">
                    <Badge tone="neutral">{t('auto.template.steps', { count: tpl.steps.length })}</Badge>
                    <span>
                      {tpl.variables.length
                        ? t('auto.template.variables', { vars: tpl.variables.join(', ') })
                        : t('auto.template.noVariables')}
                    </span>
                    <span>{t('auto.template.updated', { time: relativeTime(tpl.updated_at) })}</span>
                  </div>
                </div>
                <Button size="sm" variant="primary" onClick={() => setRunTemplate(tpl)}>
                  <Play className="h-3.5 w-3.5" /> {t('auto.template.run')}
                </Button>
                <IconButton size="sm" label={t('auto.template.delete')} onClick={() => setDeleteTarget(tpl)}>
                  <Trash2 className="h-3.5 w-3.5" />
                </IconButton>
              </div>
            ))}
          </div>
        ))}

      {tab === 'runs' &&
        (activeRunId ? (
          <RunView runId={activeRunId} onBack={() => setActiveRunId(null)} />
        ) : (
          <EmptyState
            icon={<Play className="h-5 w-5" />}
            title={t('auto.runs.empty.title')}
            description={t('auto.runs.empty.desc')}
          />
        ))}

      {tab === 'shop-check' &&
        (activeShopRunId ? (
          <ShopCheckRunView runId={activeShopRunId} onBack={() => setActiveShopRunId(null)} />
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-2xs text-ink-muted">{t('shopchk.subtitle')}</p>
              <Button variant="primary" size="sm" onClick={() => setShopWizardOpen(true)}>
                <ShieldCheck className="h-3.5 w-3.5" /> {t('shopchk.newCheck')}
              </Button>
            </div>
            {shopRuns.isLoading ? (
              <LoadingBlock label={t('shopchk.run.loading')} />
            ) : (shopRuns.data?.items.length ?? 0) === 0 ? (
              <EmptyState
                icon={<ShieldCheck className="h-5 w-5" />}
                title={t('shopchk.empty.title')}
                description={t('shopchk.empty.desc')}
                action={
                  <Button variant="primary" size="sm" onClick={() => setShopWizardOpen(true)}>
                    <ShieldCheck className="h-3.5 w-3.5" /> {t('shopchk.newCheck')}
                  </Button>
                }
              />
            ) : (
              <div className="space-y-2">
                {shopRuns.data?.items.map((run) => (
                  <button
                    key={run.id}
                    type="button"
                    onClick={() => setActiveShopRunId(run.id)}
                    className="flex w-full items-center gap-3 rounded-lg border border-line bg-surface p-3 text-left hover:border-line-strong"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-medium text-ink">
                        {t('shopchk.run.summaryLine', {
                          total: run.total_emails,
                          workers: run.worker_count,
                        })}
                      </p>
                      <p className="text-2xs text-ink-faint">{relativeTime(run.created_at)}</p>
                    </div>
                    <span className="shrink-0 text-2xs text-ink-muted">
                      {t('shopchk.run.matchedShort', {
                        matched: run.result_counts.phone_otp_required ?? 0,
                      })}
                    </span>
                    <Badge
                      tone={
                        run.status === 'completed'
                          ? 'success'
                          : run.status === 'completed_with_issues'
                            ? 'warning'
                            : run.status === 'failed'
                              ? 'danger'
                              : ['queued', 'preparing', 'running'].includes(run.status)
                                ? 'info'
                                : 'neutral'
                      }
                    >
                      {t(`shopchk.status.${run.status}` as TranslationKey)}
                    </Badge>
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}

      {tab === 'credentials' && <CredentialsPanel />}

      <ShopCheckWizard
        open={shopWizardOpen}
        onClose={() => setShopWizardOpen(false)}
        onStarted={(runId) => {
          setActiveShopRunId(runId);
          setTab('shop-check');
        }}
      />
      <RecordDialog open={recordOpen} onClose={() => setRecordOpen(false)} />
      <RunWizard
        template={runTemplate}
        onClose={() => setRunTemplate(null)}
        onStarted={(runId) => {
          setActiveRunId(runId);
          setTab('runs');
        }}
      />
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget)
            deleteTemplate.mutate(deleteTarget.id, { onSuccess: () => setDeleteTarget(null) });
        }}
        title={t('auto.template.delete.title')}
        message={t('auto.template.delete.msg', { name: deleteTarget?.name ?? '' })}
        confirmLabel={t('auto.template.delete')}
        tone="danger"
        loading={deleteTemplate.isPending}
      />
    </div>
    </div>
  );
}
