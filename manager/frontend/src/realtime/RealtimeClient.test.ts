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
