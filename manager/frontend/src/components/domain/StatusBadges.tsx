import type { ProxyHealth, ProxyReputation, RuntimeState } from '@/types/api';
import { Badge, StatusDot, type Tone } from '@/components/ui/Badge';
import { useT, type TranslationKey } from '@/i18n';

const RUNTIME: Record<RuntimeState, { tone: Tone; labelKey: TranslationKey; pulse?: boolean }> = {
  stopped: { tone: 'neutral', labelKey: 'enum.runtime.stopped' },
  starting: { tone: 'info', labelKey: 'enum.runtime.starting', pulse: true },
  running: { tone: 'success', labelKey: 'enum.runtime.running', pulse: true },
  stopping: { tone: 'warning', labelKey: 'enum.runtime.stopping', pulse: true },
  crashed: { tone: 'danger', labelKey: 'enum.runtime.crashed' },
};

export function RuntimeBadge({ state }: { state: RuntimeState }) {
  const t = useT();
  const config = RUNTIME[state];
  return (
    <Badge tone={config.tone}>
      <StatusDot tone={config.tone} pulse={config.pulse} />
      {t(config.labelKey)}
    </Badge>
  );
}

const HEALTH: Record<ProxyHealth, { tone: Tone; labelKey: TranslationKey }> = {
  healthy: { tone: 'success', labelKey: 'enum.health.healthy' },
  degraded: { tone: 'warning', labelKey: 'enum.health.degraded' },
  unreachable: { tone: 'danger', labelKey: 'enum.health.unreachable' },
  untested: { tone: 'neutral', labelKey: 'enum.health.untested' },
  unknown: { tone: 'neutral', labelKey: 'enum.health.unknown' },
};

export function ProxyHealthDot({ health }: { health: ProxyHealth }) {
  const t = useT();
  const config = HEALTH[health];
  const label = t(config.labelKey);
  return (
    <span className="inline-flex items-center gap-1.5" title={label}>
      <StatusDot tone={config.tone} />
      <span className="text-2xs text-ink-muted">{label}</span>
    </span>
  );
}

const REPUTATION: Record<ProxyReputation, Tone> = {
  clean: 'success',
  neutral: 'neutral',
  suspicious: 'warning',
  malicious: 'danger',
  unknown: 'neutral',
};

export function ReputationBadge({ reputation }: { reputation: ProxyReputation | null }) {
  const t = useT();
  if (!reputation) return <span className="text-ink-faint">—</span>;
  return <Badge tone={REPUTATION[reputation]}>{t(`enum.reputation.${reputation}`)}</Badge>;
}
