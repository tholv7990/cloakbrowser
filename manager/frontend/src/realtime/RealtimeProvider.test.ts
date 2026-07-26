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

describe('runtime.snapshot messages', () => {
  beforeEach(() => useRuntimeStore.setState({ runningCount: 0, messages: {} }));

  const snapshot = (runtimes: unknown[]) => ({
    event: 'runtime.snapshot' as const,
    sequence: 1,
    timestamp: '2026-07-25T00:00:00Z',
    data: { runtimes, running_session_count: 0 },
  });

  it('does not resurrect a finished run\u2019s message on every snapshot', () => {
    // A snapshot is broadcast whenever any profile changes state. Re-applying a
    // crashed run's message rewrote other rows' status when you pressed Start,
    // which read as "starting one profile re-checked every proxy".
    applyEvent(new QueryClient(), snapshot([
      { profile_id: 'p1', state: 'crashed', last_message: 'proxy_preflight_failed' },
      { profile_id: 'p2', state: 'stopped', last_message: 'stopped' },
    ]) as never);
    expect(useRuntimeStore.getState().messages).toEqual({});
  });

  it('clears stale messages for finished profiles when another profile starts', () => {
    useRuntimeStore.setState({
      messages: {
        finished: 'running',
        crashed: 'Testing proxy',
      },
    });

    applyEvent(new QueryClient(), snapshot([
      { profile_id: 'active', state: 'starting', last_message: 'Testing proxy' },
      { profile_id: 'finished', state: 'stopped', last_message: 'stopped' },
      { profile_id: 'crashed', state: 'crashed', last_message: 'proxy_preflight_failed' },
    ]) as never);

    expect(useRuntimeStore.getState().messages).toEqual({
      active: 'Testing proxy',
    });
  });

  it('does not overwrite stopped rows with historical terminal states', () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(['profiles'], {
      items: [
        { id: 'active', runtime_state: 'stopped' },
        { id: 'old-crash', runtime_state: 'stopped' },
      ],
      page: 1,
      pages: 1,
      total: 2,
      page_size: 25,
    });

    applyEvent(queryClient, snapshot([
      { profile_id: 'active', state: 'starting', last_message: 'Testing proxy' },
      { profile_id: 'old-crash', state: 'crashed', last_message: 'browser_crashed' },
    ]) as never);

    expect(queryClient.getQueryData<{ items: Array<{ id: string; runtime_state: string }> }>(
      ['profiles'],
    )?.items).toEqual([
      { id: 'active', runtime_state: 'starting' },
      { id: 'old-crash', runtime_state: 'stopped' },
    ]);
  });

  it('clears a row live message when its runtime becomes terminal', () => {
    useRuntimeStore.setState({ messages: { p1: 'running' } });

    applyEvent(new QueryClient(), {
      event: 'profile.runtime.changed',
      sequence: 2,
      timestamp: '2026-07-25T00:00:01Z',
      data: {
        profile_id: 'p1',
        runtime_state: 'stopped',
        message: 'stopped',
      },
    });

    expect(useRuntimeStore.getState().messages).toEqual({});
  });

  it('still shows the status of a run that is under way', () => {
    applyEvent(new QueryClient(), snapshot([
      { profile_id: 'p1', state: 'starting', last_message: 'Testing proxy…' },
      { profile_id: 'p2', state: 'running', last_message: 'running' },
    ]) as never);
    expect(useRuntimeStore.getState().messages).toEqual({
      p1: 'Testing proxy…',
      p2: 'running',
    });
  });
});
