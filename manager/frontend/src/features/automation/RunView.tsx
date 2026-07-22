import { ArrowLeft, Check, Play, RotateCcw, Square } from 'lucide-react';
import type { AutomationRunItem, RunItemStatus } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Badge, type Tone } from '@/components/ui/Badge';
import { LoadingBlock, ErrorState } from '@/components/ui/states';
import { useT, type TranslationKey } from '@/i18n';
import {
  useCancelRun,
  useContinueRunProfile,
  useMarkRunProfileCompleted,
  useRetryRunProfile,
  useRun,
} from './api';

const ITEM_TONE: Record<RunItemStatus, Tone> = {
  pending: 'neutral',
  running: 'info',
  attention: 'warning',
  completed: 'success',
  failed: 'danger',
  cancelled: 'neutral',
};
const ITEM_KEY: Record<RunItemStatus, TranslationKey> = {
  pending: 'auto.item.pending',
  running: 'auto.item.running',
  attention: 'auto.item.attention',
  completed: 'auto.item.completed',
  failed: 'auto.item.failed',
  cancelled: 'auto.item.cancelled',
};

export function RunView({ runId, onBack }: { runId: string; onBack: () => void }) {
  const t = useT();
  const run = useRun(runId);
  const cancel = useCancelRun();
  const cont = useContinueRunProfile();
  const retry = useRetryRunProfile();
  const markDone = useMarkRunProfileCompleted();

  if (run.isLoading) return <LoadingBlock label="…" />;
  if (run.isError || !run.data)
    return (
      <ErrorState
        message={(run.error as Error)?.message ?? 'Error'}
        onRetry={() => run.refetch()}
      />
    );

  const data = run.data;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-1 text-2xs text-ink-muted hover:text-ink"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> {t('auto.run.back')}
        </button>
        {data.status === 'running' && (
          <Button
            size="sm"
            variant="danger"
            onClick={() => cancel.mutate(runId)}
            loading={cancel.isPending}
          >
            <Square className="h-3.5 w-3.5" /> {t('auto.run.cancel')}
          </Button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface p-3">
        <span className="font-display text-[15px] font-semibold text-ink">{data.template_name}</span>
        <Badge
          tone={
            data.status === 'completed'
              ? 'success'
              : data.status === 'failed'
                ? 'danger'
                : data.status === 'running'
                  ? 'info'
                  : 'neutral'
          }
        >
          {t(`auto.runStatus.${data.status}` as TranslationKey)}
        </Badge>
        <span className="text-2xs text-ink-muted">
          {t('auto.run.progress', { completed: data.completed_count, total: data.total })}
        </span>
        {data.attention_count > 0 && (
          <span className="text-2xs text-warning">
            {t('auto.run.needAttention', { count: data.attention_count })}
          </span>
        )}
      </div>

      <div className="divide-y divide-line rounded-md border border-line">
        {data.items.map((item) => (
          <RunRow
            key={item.profile_id}
            item={item}
            t={t}
            onContinue={() => cont.mutate({ runId, profileId: item.profile_id })}
            onRetry={() => retry.mutate({ runId, profileId: item.profile_id })}
            onMarkDone={() => markDone.mutate({ runId, profileId: item.profile_id })}
          />
        ))}
      </div>
    </div>
  );
}

function RunRow({
  item,
  t,
  onContinue,
  onRetry,
  onMarkDone,
}: {
  item: AutomationRunItem;
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string;
  onContinue: () => void;
  onRetry: () => void;
  onMarkDone: () => void;
}) {
  const pct = Math.round((item.current_step / Math.max(1, item.total_steps)) * 100);
  const note = item.attention_reason ?? item.error ?? item.message;
  return (
    <div className="flex items-center gap-3 px-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[13px] font-medium text-ink">{item.profile_name}</span>
          <Badge tone={ITEM_TONE[item.status]}>{t(ITEM_KEY[item.status])}</Badge>
        </div>
        <div className="mt-1 flex items-center gap-2">
          <div className="h-1 w-28 overflow-hidden rounded-full bg-line">
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-2xs text-ink-faint">
            {t('auto.run.step', { current: item.current_step, total: item.total_steps })}
          </span>
        </div>
        {note && (
          <p
            className={`mt-0.5 truncate text-2xs ${
              item.error ? 'text-danger' : item.attention_reason ? 'text-warning' : 'text-ink-faint'
            }`}
          >
            {note}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {item.status === 'attention' && (
          <Button size="sm" variant="primary" onClick={onContinue}>
            <Play className="h-3.5 w-3.5" /> {t('auto.item.continue')}
          </Button>
        )}
        {item.status === 'failed' && (
          <>
            <Button size="sm" variant="secondary" onClick={onRetry}>
              <RotateCcw className="h-3.5 w-3.5" /> {t('auto.item.retry')}
            </Button>
            <Button size="sm" variant="ghost" onClick={onMarkDone}>
              <Check className="h-3.5 w-3.5" /> {t('auto.item.markDone')}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
