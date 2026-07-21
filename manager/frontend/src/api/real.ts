/** Live backend adapter — maps ApiAdapter calls onto the REST contract (§13). */
import type {
  AppBootstrap,
  AppVersion,
  AuthStatus,
  BulkProfileRequest,
  BulkProfileResult,
  ChangePasswordRequest,
  CookieImportPayload,
  CookieImportResult,
  DiagnosticRun,
  EmailPasswordRequest,
  Folder,
  OwnerSession,
  Paginated,
  ProfileCreatePayload,
  ProfileListParams,
  ProfileLogs,
  ProfileRead,
  ProfileUpdatePayload,
  ParsedProxy,
  Proxy,
  ProxyQualityReport,
  ProxyQuickTest,
  ProxyWritePayload,
  Settings,
  Tag,
  WorkflowStatus,
} from '@/types/api';
import type { ApiAdapter } from './adapter';
import { apiRequest } from './http';

export const realApi: ApiAdapter = {
  mode: 'real',

  authStatus: () => apiRequest<AuthStatus>('/auth/status'),
  authSetup: (payload: EmailPasswordRequest) =>
    apiRequest<OwnerSession>('/auth/setup', { method: 'POST', body: payload }),
  authLogin: (payload: EmailPasswordRequest) =>
    apiRequest<OwnerSession>('/auth/login', { method: 'POST', body: payload }),
  authSession: () => apiRequest<OwnerSession>('/auth/session'),
  authLogout: () => apiRequest('/auth/logout', { method: 'POST' }),
  authLock: () => apiRequest('/auth/lock', { method: 'POST' }),
  authChangePassword: (payload: ChangePasswordRequest) =>
    apiRequest('/auth/change-password', { method: 'POST', body: payload }),

  health: () => apiRequest('/health'),
  bootstrap: () => apiRequest<AppBootstrap>('/app/bootstrap'),
  version: () => apiRequest<AppVersion>('/app/version'),

  listProfiles: (params: ProfileListParams) =>
    apiRequest<Paginated<ProfileRead>>('/profiles', {
      query: {
        query: params.query,
        folder_id: params.folder_id,
        tag_id: params.tag_id,
        workflow_status_id: params.workflow_status_id,
        pinned: params.pinned,
        sort: params.sort,
        page: params.page,
        page_size: params.page_size,
      },
    }),
  getProfile: (id) => apiRequest<ProfileRead>(`/profiles/${id}`),
  createProfile: (payload: ProfileCreatePayload) =>
    apiRequest<ProfileRead>('/profiles', { method: 'POST', body: payload }),
  quickCreateProfile: (payload: ProfileCreatePayload) =>
    apiRequest<ProfileRead>('/profiles/quick-create', { method: 'POST', body: payload }),
  updateProfile: (id, payload: ProfileUpdatePayload) =>
    apiRequest<ProfileRead>(`/profiles/${id}`, { method: 'PATCH', body: payload }),
  duplicateProfile: (id) =>
    apiRequest<ProfileRead>(`/profiles/${id}/duplicate`, { method: 'POST' }),
  regenerateFingerprint: (id) =>
    apiRequest<ProfileRead>(`/profiles/${id}/regenerate-fingerprint`, { method: 'POST' }),
  startProfile: (id) => apiRequest<ProfileRead>(`/profiles/${id}/start`, { method: 'POST' }),
  stopProfile: (id) => apiRequest<ProfileRead>(`/profiles/${id}/stop`, { method: 'POST' }),
  focusWindow: (id) => apiRequest(`/profiles/${id}/focus-window`, { method: 'POST' }),
  moveProfileToTrash: (id) => apiRequest(`/profiles/${id}/move-to-trash`, { method: 'POST' }),
  restoreProfile: (id) => apiRequest<ProfileRead>(`/profiles/${id}/restore`, { method: 'POST' }),
  getProfileLogs: (id) => apiRequest<ProfileLogs>(`/profiles/${id}/logs`),
  exportProfile: (id) => apiRequest<Record<string, unknown>>(`/profiles/${id}/export`),
  importProfile: (payload) =>
    apiRequest<ProfileRead>('/profiles/import', { method: 'POST', body: payload }),
  importCookies: (id, payload: CookieImportPayload) =>
    apiRequest<CookieImportResult>(`/profiles/${id}/cookies/import`, {
      method: 'POST',
      body: payload,
    }),
  bulkProfiles: (request: BulkProfileRequest) =>
    apiRequest<BulkProfileResult>('/profiles/bulk', { method: 'POST', body: request }),

  listFolders: () => apiRequest<Folder[]>('/folders'),
  createFolder: (name) => apiRequest<Folder>('/folders', { method: 'POST', body: { name } }),
  renameFolder: (id, name) =>
    apiRequest<Folder>(`/folders/${id}`, { method: 'PATCH', body: { name } }),
  reorderFolders: (orderedIds) =>
    apiRequest<Folder[]>('/folders/reorder', { method: 'POST', body: { ids: orderedIds } }),
  deleteFolder: (id) => apiRequest(`/folders/${id}`, { method: 'DELETE' }),
  listTags: () => apiRequest<Tag[]>('/tags'),
  createTag: (payload) => apiRequest<Tag>('/tags', { method: 'POST', body: payload }),
  listWorkflowStatuses: () => apiRequest<WorkflowStatus[]>('/workflow-statuses'),

  listProxies: () => apiRequest<Proxy[]>('/proxies'),
  getProxy: (id) => apiRequest<Proxy>(`/proxies/${id}`),
  createProxy: (payload: ProxyWritePayload) =>
    apiRequest<Proxy>('/proxies', { method: 'POST', body: payload }),
  updateProxy: (id, payload: ProxyWritePayload) =>
    apiRequest<Proxy>(`/proxies/${id}`, { method: 'PATCH', body: payload }),
  deleteProxy: (id) => apiRequest(`/proxies/${id}`, { method: 'DELETE' }),
  parseProxy: (raw) => apiRequest<ParsedProxy>('/proxies/parse', { method: 'POST', body: { raw } }),
  quickTestProxy: (id) =>
    apiRequest<ProxyQuickTest>(`/proxies/${id}/quick-test`, { method: 'POST' }),
  qualityTestProxy: (id) =>
    apiRequest<ProxyQualityReport>(`/proxies/${id}/quality-test`, { method: 'POST' }),
  getProxyReports: (id) => apiRequest<ProxyQualityReport[]>(`/proxies/${id}/reports`),

  listDiagnostics: () => apiRequest<DiagnosticRun[]>('/diagnostics'),
  getDiagnostic: (id) => apiRequest<DiagnosticRun>(`/diagnostics/${id}`),
  runDirectGoogleControl: () =>
    apiRequest<DiagnosticRun>('/diagnostics/direct-google-control', { method: 'POST' }),
  runPixelscan: (profileId) =>
    apiRequest<DiagnosticRun>('/diagnostics/pixelscan', {
      method: 'POST',
      body: { profile_id: profileId },
    }),
  getSettings: () => apiRequest<Settings>('/settings'),
  updateSettings: (patch: Partial<Settings>) =>
    apiRequest<Settings>('/settings', { method: 'PATCH', body: patch }),
};
