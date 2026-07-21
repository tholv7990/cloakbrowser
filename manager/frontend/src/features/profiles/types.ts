import type { ProfileSort } from '@/types/api';

/** Server-supported profile filters (spec §13 GET /profiles query params). */
export interface ProfileFilters {
  folder_id: string | null;
  tag_id: string | null;
  workflow_status_id: string | null;
  pinned: boolean | null;
}

export const emptyFilters: ProfileFilters = {
  folder_id: null,
  tag_id: null,
  workflow_status_id: null,
  pinned: null,
};

export function activeFilterCount(filters: ProfileFilters): number {
  return Object.values(filters).filter((value) => value !== null).length;
}

export const DEFAULT_SORT: ProfileSort = '-updated_at';

/** Cycle a column between ascending, descending, and cleared (→ default). */
export function nextSort(current: ProfileSort, columnId: string): ProfileSort {
  const asc = columnId as ProfileSort;
  const desc = `-${columnId}` as ProfileSort;
  if (current === asc) return desc;
  if (current === desc) return DEFAULT_SORT;
  return asc;
}
