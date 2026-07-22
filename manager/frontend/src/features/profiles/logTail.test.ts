import { describe, expect, it } from 'vitest';
import type { ProfileLogEntry, ProfileLogTail } from '@/types/api';
import { mergeProfileLogTail } from './logTail';

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
  it('appends chronologically without duplicates and applies the visible bound', () => {
    const first = mergeProfileLogTail([], tail([entry('1'), entry('2')]), 3);
    const second = mergeProfileLogTail(first, tail([entry('2'), entry('3'), entry('4')]), 3);
    expect(second.map((item) => item.id)).toEqual(['2', '3', '4']);
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
