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
  profileExtensions: (id: string) => ['profile', id, 'extensions'] as const,
  folders: ['folders'] as const,
  tags: ['tags'] as const,
  statuses: ['workflow-statuses'] as const,
  extensions: ['extensions'] as const,
  proxies: ['proxies'] as const,
  proxy: (id: string) => ['proxy', id] as const,
  proxyReports: (id: string) => ['proxy', id, 'reports'] as const,
  diagnostics: ['diagnostics'] as const,
  resources: ['resources'] as const,
  monitors: ['runtime', 'monitors'] as const,
  automationTemplates: ['automation', 'templates'] as const,
  automationTemplate: (id: string) => ['automation', 'template', id] as const,
  automationRecording: (id: string) => ['automation', 'recording', id] as const,
  automationRun: (id: string) => ['automation', 'run', id] as const,
  automationCredentials: ['automation', 'credentials'] as const,
  automationFactory: ['automation', 'factory'] as const,
  shopifyStores: ['shopify', 'stores'] as const,
  shopifyStoreProfile: (id: string) => ['shopify', 'store', id, 'profile'] as const,
  shopifyAiSettings: ['shopify', 'ai-settings'] as const,
  shopifyThemes: (storeId: string) => ['shopify', 'themes', storeId] as const,
  shopifyCatalogs: ['shopify', 'catalogs'] as const,
  shopifyPlan: (planId: string) => ['shopify', 'plan', planId] as const,
  sessions: ['sessions'] as const,
  backups: ['backups'] as const,
  mediaSettings: ['media', 'settings'] as const,
  mediaAssets: ['media', 'assets'] as const,
  proxyProviders: ['proxies', 'providers'] as const,
};
