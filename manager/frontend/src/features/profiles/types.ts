import type { BrowserVersionMode, LocationSettings, ProfileSort, UserAgentMode } from '@/types/api';

export interface FingerprintOverrides {
  gpu_vendor: string | null;
  gpu_renderer: string | null;
  hardware_concurrency: number | null;
  device_memory: number | null;
  screen_width: number | null;
  screen_height: number | null;
  brand: string | null;
}

export interface ProfileValidationDraft extends FingerprintOverrides {
  browser_version_mode: BrowserVersionMode;
  browser_version: string | null;
  user_agent_mode: UserAgentMode;
  custom_user_agent: string | null;
  location: LocationSettings;
  proxy_id: string | null;
}

export type FingerprintCoherenceCode =
  | 'ua.platform_mismatch'
  | 'ua.version_mismatch'
  | 'gpu.vendor_renderer_mismatch'
  | 'gpu.platform_mismatch'
  | 'geo.timezone_mismatch'
  | 'geo.locale_mismatch';

export interface FingerprintCoherenceFinding {
  code: FingerprintCoherenceCode;
  severity: 'warning' | 'error';
  field: string;
  /** Diagnostic fallback for unknown clients; the UI localizes from `code`. */
  message: string;
}

export interface FingerprintCoherenceResult {
  status: 'coherent' | 'warning' | 'error';
  findings: FingerprintCoherenceFinding[];
}

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
