import { useCallback, useEffect, useState } from 'react';
import { useRealtimeEvent } from '@/hooks/useRealtimeEvent';

/** Live progress bar fed by proxy.test.progress events (spec §8, §14). */
export function ProxyTestProgress({
  proxyId,
  kind,
  active,
}: {
  proxyId: string;
  kind: 'quick' | 'quality';
  active: boolean;
}) {
  const [state, setState] = useState<{ phase: string; progress: number } | null>(null);

  useEffect(() => {
    if (active) setState({ phase: 'Starting…', progress: 0 });
    else setState(null);
  }, [active]);

  const handler = useCallback(
    (event: { data: { proxy_id: string; kind: string; phase: string; progress: number } }) => {
      if (event.data.proxy_id === proxyId && event.data.kind === kind) {
        setState({ phase: event.data.phase, progress: event.data.progress });
      }
    },
    [proxyId, kind],
  );
  useRealtimeEvent('proxy.test.progress', handler);

  if (!active || !state) return null;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-2xs text-ink-muted">
        <span>{state.phase}</span>
        <span>{Math.round(state.progress * 100)}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-sunken">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-200"
          style={{ width: `${Math.max(4, state.progress * 100)}%` }}
        />
      </div>
    </div>
  );
}
