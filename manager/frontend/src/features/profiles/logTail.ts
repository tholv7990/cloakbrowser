import type { ProfileLogEntry, ProfileLogTail } from '@/types/api';

export function mergeProfileLogTail(
  previous: ProfileLogEntry[],
  response: ProfileLogTail,
  limit: number,
): ProfileLogEntry[] {
  const source = response.reset ? response.items : [...previous, ...response.items];
  const unique = new Map<string, ProfileLogEntry>();
  for (const item of source) unique.set(item.id, item);
  return [...unique.values()]
    .sort(
      (left, right) =>
        left.created_at.localeCompare(right.created_at) || left.id.localeCompare(right.id),
    )
    .slice(-limit);
}
