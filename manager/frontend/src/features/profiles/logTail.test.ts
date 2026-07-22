import { describe, expect, it } from 'vitest';
import type { ProfileLogEntry, ProfileLogTail } from '@/types/api';
import { mergeProfileLogTail, synchronizeTailCursor } from './logTail';

const entry = (id: string): ProfileLogEntry => ({
  id,
  profile_id: 'profile-1',
  created_at: `2026-07-22T00:00:0${id}Z`,
  level: 'info',
  event: 'runtime.ready',
  message: id,
});

const tail = (items: ProfileLogEntry[], reset = false): ProfileLogTail => ({
  items,
  next_cursor: `cursor-${items.at(-1)?.id ?? 'none'}`,
  reset,
});

describe('mergeProfileLogTail', () => {
  it('resets the opaque cursor synchronously when profile or limit key changes', () => {
    const current = { key: 'profile-1:20', cursor: 'opaque-cursor' };
    expect(synchronizeTailCursor(current, 'profile-1:20')).toBe(current);
    expect(synchronizeTailCursor(current, 'profile-2:20')).toEqual({
      key: 'profile-2:20',
      cursor: null,
    });
  });

  it('appends chronologically without duplicates and applies the visible bound', () => {
    const first = mergeProfileLogTail([], tail([entry('1'), entry('2')]), 3);
    const second = mergeProfileLogTail(first, tail([entry('2'), entry('3'), entry('4')]), 3);
    expect(second.map((item) => item.id)).toEqual(['2', '3', '4']);
  });

  it('preserves backend monotonic delivery order instead of timestamp or UUID order', () => {
    const first = {
      ...entry('ffffffff-ffff-4fff-8fff-ffffffffffff'),
      created_at: '2026-07-22T00:00:02Z',
    };
    const laterSequence = {
      ...entry('00000000-0000-4000-8000-000000000001'),
      created_at: '2026-07-22T00:00:01Z',
    };
    const merged = mergeProfileLogTail([first], tail([first, laterSequence]), 20);
    expect(merged.map((item) => item.id)).toEqual([first.id, laterSequence.id]);
  });

  it('replaces local history when the backend resets a stale cursor', () => {
    const merged = mergeProfileLogTail(
      [entry('1'), entry('2')],
      tail([entry('8'), entry('9')], true),
      20,
    );
    expect(merged.map((item) => item.id)).toEqual(['8', '9']);
  });
});
