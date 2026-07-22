import { describe, expect, it } from 'vitest';
import { normalizeRealtimeFrame } from './RealtimeClient';

describe('normalizeRealtimeFrame', () => {
  it('maps real runtime snapshots including the real running count', () => {
    expect(
      normalizeRealtimeFrame({
        sequence: 3,
        type: 'runtime.snapshot',
        runtimes: [{ profile_id: 'p-1', state: 'running', last_message: 'ready' }],
        running_session_count: 1,
      }),
    ).toMatchObject({
      event: 'runtime.snapshot',
      sequence: 3,
      data: { running_session_count: 1 },
    });
  });

  it('keeps only the newest runtime per profile in newest-first order', () => {
    const event = normalizeRealtimeFrame({
      sequence: 4,
      type: 'runtime.snapshot',
      runtimes: [
        {
          id: 'new-a',
          profile_id: 'p-1',
          state: 'running',
          last_message: 'new',
          created_at: '2026-07-22T02:00:00Z',
        },
        {
          id: 'other',
          profile_id: 'p-2',
          state: 'stopped',
          last_message: null,
          created_at: '2026-07-22T01:00:00Z',
        },
        {
          id: 'old-a',
          profile_id: 'p-1',
          state: 'stopped',
          last_message: 'old',
          created_at: '2026-07-21T23:00:00Z',
        },
      ],
      running_session_count: 1,
    });

    expect(event?.event).toBe('runtime.snapshot');
    if (event?.event !== 'runtime.snapshot') throw new Error('unexpected event');
    expect(event.data.runtimes.map((runtime) => runtime.id)).toEqual(['new-a', 'other']);
  });

  it('maps safe diagnostic progress frames from the backend', () => {
    expect(
      normalizeRealtimeFrame({
        sequence: 4,
        type: 'diagnostic.progress',
        diagnostic: {
          id: 'd-1',
          profile_id: 'p-1',
          kind: 'pixelscan',
          status: 'running',
          progress: 55,
          error_code: null,
        },
      }),
    ).toMatchObject({
      event: 'diagnostic.progress',
      data: { diagnostic_id: 'd-1', status: 'running', progress: 55 },
    });
  });
});
