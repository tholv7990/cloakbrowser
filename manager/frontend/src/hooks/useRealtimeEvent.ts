import { useEffect } from 'react';
import type { AppEvent, EventName } from '@/types/events';
import { useRealtime } from '@/realtime/RealtimeProvider';

/**
 * Subscribe to a single realtime event by name. Used by views that need the raw
 * stream (e.g. proxy-test progress) on top of the cache updates the provider
 * already applies.
 */
export function useRealtimeEvent<E extends EventName>(
  name: E,
  handler: (event: Extract<AppEvent, { event: E }>) => void,
): void {
  const { subscribe } = useRealtime();
  useEffect(() => {
    return subscribe((event) => {
      if (event.event === name) handler(event as Extract<AppEvent, { event: E }>);
    });
  }, [name, handler, subscribe]);
}
