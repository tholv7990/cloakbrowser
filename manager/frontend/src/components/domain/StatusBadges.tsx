import type { ProxyHealth, ProxyReputation, RuntimeState } from '@/types/api';
import { Badge, StatusDot, type Tone } from '@/components/ui/Badge';

const RUNTIME: Record<RuntimeState, { tone: Tone; label: string; pulse?: boolean }> = {
  stopped: { tone: 'neutral', label: 'Stopped' },
  starting: { tone: 'info', label: 'Starting', pulse: true },
  running: { tone: 'success', label: 'Running', pulse: true },
  stopping: { tone: 'warning', label: 'Stopping', pulse: true },
  crashed: { tone: 'danger', label: 'Crashed' },
};

export function RuntimeBadge({ state }: { state: RuntimeState }) {
  const config = RUNTIME[state];
  return (
    <Badge tone={config.tone}>
      <StatusDot tone={config.tone} pulse={config.pulse} />
      {config.label}
    </Badge>
  );
}

const HEALTH: Record<ProxyHealth, { tone: Tone; label: string }> = {
  healthy: { tone: 'success', label: 'Healthy' },
  degraded: { tone: 'warning', label: 'Degraded' },
  unreachable: { tone: 'danger', label: 'Unreachable' },
  untested: { tone: 'neutral', label: 'Untested' },
  unknown: { tone: 'neutral', label: 'Unknown' },
};

export function ProxyHealthDot({ health }: { health: ProxyHealth }) {
  const config = HEALTH[health];
  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={`Proxy ${config.label.toLowerCase()}`}
    >
      <StatusDot tone={config.tone} />
      <span className="text-2xs text-ink-muted">{config.label}</span>
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
  if (!reputation) return <span className="text-ink-faint">—</span>;
  return (
    <Badge tone={REPUTATION[reputation]}>
      {reputation.charAt(0).toUpperCase() + reputation.slice(1)}
    </Badge>
  );
}
