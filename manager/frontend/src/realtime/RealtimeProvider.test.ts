import { QueryClient } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useRuntimeStore } from '@/app/runtimeStore';
import { applyEvent } from './RealtimeProvider';

describe('applyEvent runtime invalidation', () => {
  beforeEach(() => useRuntimeStore.setState({ runningCount: 0, messages: {} }));

  it('refreshes folder counts for runtime changes and snapshots', () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

    applyEvent(queryClient, {
      event: 'runtime.snapshot',
      sequence: 1,
      timestamp: '2026-07-22T00:00:00Z',
      data: { runtimes: [], running_session_count: 0 },
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['folders'] });

    applyEvent(queryClient, {
      event: 'profile.runtime.changed',
      sequence: 2,
      timestamp: '2026-07-22T00:00:01Z',
      data: { profile_id: 'p-1', runtime_state: 'running' },
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['folders'] });
  });
});
