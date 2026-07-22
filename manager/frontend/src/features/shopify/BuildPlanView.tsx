import { useState } from 'react';
import { ArrowLeft, ExternalLink } from 'lucide-react';
import type { BuildPlanStatus, PlanStepStatus } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Badge, type Tone } from '@/components/ui/Badge';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { LoadingBlock, ErrorState } from '@/components/ui/states';
import { useT, type TranslationKey } from '@/i18n';
import { useBuildPlan, useExecuteBuildPlan } from './api';

const PLAN_TONE: Record<BuildPlanStatus, Tone> = {
  staged: 'neutral',
  running: 'info',
  completed: 'success',
  partial: 'warning',
  failed: 'danger',
};

const STEP_TONE: Record<PlanStepStatus, Tone> = {
  planned: 'neutral',
  ready: 'neutral',
  blocked: 'warning',
  running: 'info',
  completed: 'success',
  failed: 'danger',
};

export function BuildPlanView({
  storeId,
  planId,
  onBack,
}: {
  storeId: string;
  planId: string;
  onBack: () => void;
}) {
  const t = useT();
  const plan = useBuildPlan(storeId, planId);
  const execute = useExecuteBuildPlan(storeId);
  const [confirmOpen, setConfirmOpen] = useState(false);

  if (plan.isLoading) return <LoadingBlock label="…" />;
  if (plan.isError || !plan.data)
    return (
      <ErrorState
        message={(plan.error as Error)?.message ?? 'Error'}
        onRetry={() => plan.refetch()}
      />
    );

  const data = plan.data;
  const nonBlocked = data.steps.filter((step) => step.status !== 'blocked');
  const completed = nonBlocked.filter((step) => step.status === 'completed').length;
  const pct = nonBlocked.length ? Math.round((completed / nonBlocked.length) * 100) : 0;

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={onBack}
        className="flex items-center gap-1 text-2xs text-ink-muted hover:text-ink"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> {t('shop.plan.back')}
      </button>

      <div className="rounded-lg border border-line bg-surface p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-display text-[15px] font-semibold text-ink">
            {t('shop.plan.title')}
          </span>
          <Badge tone={PLAN_TONE[data.status]}>
            {t(`shop.planStatus.${data.status}` as TranslationKey)}
          </Badge>
          <Badge tone="neutral">{t('shop.plan.draftOnly')}</Badge>
        </div>
        <p className="mt-1 text-2xs text-ink-muted">
          {t('shop.plan.summary', {
            niche: data.niche,
            products: data.product_count,
            theme: data.theme_name,
          })}
        </p>

        <div className="mt-3 flex items-center gap-2">
          <div className="h-1 flex-1 overflow-hidden rounded-full bg-line">
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="shrink-0 text-2xs tabular-nums text-ink-faint">
            {completed}/{nonBlocked.length}
          </span>
        </div>

        {(data.admin_url || data.preview_url) && (
          <div className="mt-3 flex flex-wrap gap-2">
            {data.admin_url && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => window.open(data.admin_url!, '_blank', 'noopener,noreferrer')}
              >
                <ExternalLink className="h-3.5 w-3.5" /> {t('shop.plan.admin')}
              </Button>
            )}
            {data.preview_url && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => window.open(data.preview_url!, '_blank', 'noopener,noreferrer')}
              >
                <ExternalLink className="h-3.5 w-3.5" /> {t('shop.plan.preview')}
              </Button>
            )}
          </div>
        )}
      </div>

      {data.status === 'staged' && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line bg-surface p-3">
          <p className="text-2xs text-ink-muted">{t('shop.plan.staged')}</p>
          <Button variant="primary" size="sm" onClick={() => setConfirmOpen(true)}>
            {t('shop.plan.execute')}
          </Button>
        </div>
      )}

      <div className="divide-y divide-line rounded-lg border border-line">
        {data.steps.map((step) => {
          const note = step.error ?? step.reason;
          return (
            <div key={step.key} className="flex items-center gap-3 px-3 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-[13px] font-medium text-ink">
                    {t(`shop.step.${step.key}` as TranslationKey)}
                  </span>
                  <Badge tone={STEP_TONE[step.status]}>
                    {t(`shop.stepStatus.${step.status}` as TranslationKey)}
                  </Badge>
                </div>
                {note && (
                  <p
                    className={`mt-0.5 truncate text-2xs ${
                      step.error ? 'text-danger' : 'text-ink-faint'
                    }`}
                  >
                    {note}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={() =>
          execute.mutate(planId, { onSuccess: () => setConfirmOpen(false) })
        }
        title={t('shop.plan.executeConfirm.title')}
        message={t('shop.plan.executeConfirm.msg')}
        confirmLabel={t('shop.plan.execute')}
        tone="primary"
        loading={execute.isPending}
      />
    </div>
  );
}
