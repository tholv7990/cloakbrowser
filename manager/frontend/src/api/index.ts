/**
 * Single entry point for server access. UI/feature code imports `api` from here
 * and never touches a concrete adapter, so mock and real stay interchangeable
 * (chosen by VITE_API_MODE). `queryKeys` centralizes TanStack Query cache keys.
 */
import type { ApiAdapter } from './adapter';
import { API_MODE } from './config';
import { realApi } from './real';
import { mockApi } from '@/mocks/mockApi';

export const api: ApiAdapter = API_MODE === 'real' ? realApi : mockApi;

export { ApiError } from './http';
export type { ApiAdapter } from './adapter';

import type { ProfileListParams } from '@/types/api';

export const queryKeys = {
  bootstrap: ['bootstrap'] as const,
  version: ['version'] as const,
  settings: ['settings'] as const,
  profiles: (params: ProfileListParams) => ['profiles', params] as const,
  profilesRoot: ['profiles'] as const,
  profile: (id: string) => ['profile', id] as const,
  profileLogs: (id: string) => ['profile', id, 'logs'] as const,
  folders: ['folders'] as const,
  tags: ['tags'] as const,
  statuses: ['workflow-statuses'] as const,
  proxies: ['proxies'] as const,
  proxy: (id: string) => ['proxy', id] as const,
  proxyReports: (id: string) => ['proxy', id, 'reports'] as const,
  diagnostics: ['diagnostics'] as const,
};
