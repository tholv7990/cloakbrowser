import type { ProxyHealth, ProxyReputation, RuntimeState } from '@/types/api';
import { Badge, StatusDot, type Tone } from '@/components/ui/Badge';
import { cn } from '@/lib/cn';
import { useT, type TranslationKey } from '@/i18n';

const RUNTIME: Record<RuntimeState, { tone: Tone; labelKey: TranslationKey; pulse?: boolean }> = {
  queued: { tone: 'info', labelKey: 'enum.runtime.queued', pulse: true },
  stopped: { tone: 'neutral', labelKey: 'enum.runtime.stopped' },
  starting: { tone: 'info', labelKey: 'enum.runtime.starting', pulse: true },
  running: { tone: 'success', labelKey: 'enum.runtime.running', pulse: true },
  stopping: { tone: 'warning', labelKey: 'enum.runtime.stopping', pulse: true },
  crashed: { tone: 'danger', labelKey: 'enum.runtime.crashed' },
  detached: { tone: 'warning', labelKey: 'enum.runtime.detached' },
};

/**
 * Plasma mark for the "profile open" (running) state — a bright core inside two
 * crossed orbital arcs, energized: the arcs orbit and the halo breathes. Drawn in
 * currentColor so it inherits the running badge's success tone. Motion is dropped
 * for `prefers-reduced-motion`.
 */
export function PlasmaIcon({ size = 13, className }: { size?: number; className?: string }) {
  const spin = { transformBox: 'fill-box', transformOrigin: 'center' } as const;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={cn('shrink-0', className)}
    >
      <circle
        cx="12"
        cy="12"
        r="10"
        fill="currentColor"
        className="animate-pulse opacity-20 [animation-duration:2.4s] motion-reduce:animate-none"
        style={spin}
      />
      <g
        className="animate-spin [animation-duration:9s] motion-reduce:animate-none"
        style={spin}
        stroke="currentColor"
        strokeWidth="1.4"
      >
        <ellipse cx="12" cy="12" rx="9" ry="3.4" transform="rotate(28 12 12)" />
        <ellipse cx="12" cy="12" rx="9" ry="3.4" transform="rotate(-28 12 12)" opacity="0.65" />
      </g>
      <circle cx="12" cy="12" r="3.2" fill="currentColor" />
    </svg>
  );
}

export function RuntimeBadge({ state }: { state: RuntimeState }) {
  const t = useT();
  const config = RUNTIME[state];
  return (
    <Badge tone={config.tone}>
      {state === 'running' ? (
        <PlasmaIcon className="-ml-0.5" />
      ) : (
        <StatusDot tone={config.tone} pulse={config.pulse} />
      )}
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
