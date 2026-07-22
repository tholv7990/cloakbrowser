import type { ProfileLogEntry, ProfileLogTail } from '@/types/api';

export interface TailCursorState {
  key: string;
  cursor: string | null;
}

export function synchronizeTailCursor(current: TailCursorState, key: string): TailCursorState {
  return current.key === key ? current : { key, cursor: null };
}

export function mergeProfileLogTail(
  previous: ProfileLogEntry[],
  response: ProfileLogTail,
  limit: number,
): ProfileLogEntry[] {
  const source = response.reset ? response.items : [...previous, ...response.items];
  const unique = new Map<string, ProfileLogEntry>();
  for (const item of source) unique.set(item.id, item);
  return [...unique.values()].slice(-limit);
}
