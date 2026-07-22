/** Live backend adapter — maps ApiAdapter calls onto the REST contract (§13). */
import type {
  AppBootstrap,
  AppVersion,
  AuthStatus,
  AiImageSettings,
  AutomationRecording,
  AutomationRun,
  AutomationTemplate,
  BackupArchive,
  BuildPlan,
  BulkProfileRequest,
  BulkProfileResult,
  ChangePasswordRequest,
  CookieImportPayload,
  CookieImportResult,
  CredentialPoolSummary,
  DiagnosticRun,
  Extension,
  GenerateProxiesResult,
  MediaAsset,
  MediaSettings,
  ProductCatalog,
  ProductCsvInspection,
  ProfileFactoryJob,
  ProxyProvider,
  RuntimeSessionRecord,
  ShopifyStore,
  StoreProfile,
  ThemeLibrary,
  EmailPasswordRequest,
  Folder,
  OwnerSession,
  Paginated,
  ProfileCreatePayload,
  ProfileListParams,
  ProfileLogs,
  ProfileLogTail,
  ProfileExtensionAssignment,
  ProfileRead,
  ProfileImportResult,
  ProfileUpdatePayload,
  ParsedProxy,
  Proxy,
  ProxyQualityReport,
  ProxyQuickTest,
  ProxyWritePayload,
  ResourceSnapshot,
  Settings,
  Tag,
  WorkflowStatus,
} from '@/types/api';
import type { ApiAdapter } from './adapter';
import { apiDownload, apiRequest } from './http';

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
  startProfile: (id) => apiRequest<void>(`/profiles/${id}/start`, { method: 'POST' }),
  stopProfile: (id) => apiRequest<void>(`/profiles/${id}/stop`, { method: 'POST' }),
  focusWindow: (id) => apiRequest(`/profiles/${id}/focus-window`, { method: 'POST' }),
  moveProfileToTrash: (id) => apiRequest(`/profiles/${id}/move-to-trash`, { method: 'POST' }),
  restoreProfile: (id) => apiRequest<ProfileRead>(`/profiles/${id}/restore`, { method: 'POST' }),
  getProfileLogs: (id, params = {}) =>
    apiRequest<ProfileLogs>(`/profiles/${id}/logs`, { query: params }),
  getProfileLogTail: (id, params = {}) =>
    apiRequest<ProfileLogTail>(`/profiles/${id}/logs/tail`, { query: params }),
  exportProfile: (id) => apiDownload(`/profiles/${id}/export`),
  importProfile: (payload) =>
    apiRequest<ProfileImportResult>('/profiles/import', { method: 'POST', body: payload }),
  importCookies: (id, payload: CookieImportPayload) =>
    apiRequest<CookieImportResult>(`/profiles/${id}/cookies/import`, {
      method: 'POST',
      body: payload,
    }),
  exportCookies: (id, format) =>
    apiDownload(`/profiles/${id}/cookies/export`, { query: { format } }),
  openProfileDirectory: (id) =>
    apiRequest<{ profile_directory: string }>(`/profiles/${id}/open-directory`, {
      method: 'POST',
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

  listExtensions: () => apiRequest<Extension[]>('/extensions'),
  registerExtension: (directory) =>
    apiRequest<Extension>('/extensions', { method: 'POST', body: { directory } }),
  updateExtension: (id, patch) =>
    apiRequest<Extension>(`/extensions/${id}`, { method: 'PATCH', body: patch }),
  unregisterExtension: (id) => apiRequest<void>(`/extensions/${id}`, { method: 'DELETE' }),
  getProfileExtensions: (id) =>
    apiRequest<ProfileExtensionAssignment>(`/profiles/${id}/extensions`),
  setProfileExtensions: (id, extensionIds) =>
    apiRequest<ProfileExtensionAssignment>(`/profiles/${id}/extensions`, {
      method: 'PUT',
      body: { extension_ids: extensionIds },
    }),

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

  listDiagnostics: (params = {}) =>
    apiRequest<Paginated<DiagnosticRun>>('/diagnostics', {
      query: {
        profile: params.profile,
        kind: params.kind,
        status: params.status,
        page: params.page,
        page_size: params.page_size,
      },
    }),
  getDiagnostic: (id) => apiRequest<DiagnosticRun>(`/diagnostics/${id}`),
  runDirectGoogleControl: () =>
    apiRequest<DiagnosticRun>('/diagnostics/direct-google-control', { method: 'POST' }),
  runPixelscan: (profileId) =>
    apiRequest<DiagnosticRun>('/diagnostics/pixelscan', {
      method: 'POST',
      body: { profile_id: profileId },
    }),
  runDiagnostic: (kind, profileId) =>
    apiRequest<DiagnosticRun>(`/diagnostics/${kind === 'google_search' ? 'google-search' : kind}`, {
      method: 'POST',
      body: { profile_id: profileId },
    }),
  cancelDiagnostic: (id) =>
    apiRequest<DiagnosticRun>(`/diagnostics/${id}/cancel`, { method: 'POST' }),
  getSettings: () => apiRequest<Settings>('/settings'),
  updateSettings: (patch: Partial<Settings>) =>
    apiRequest<Settings>('/settings', { method: 'PATCH', body: patch }),
  checkBrowserUpdate: () =>
    apiRequest<Settings>('/settings/browser/check-update', { method: 'POST' }),

  getResources: () => apiRequest<ResourceSnapshot>('/resources'),

  listTemplates: () => apiRequest<AutomationTemplate[]>('/automations/templates'),
  getTemplate: (id) => apiRequest<AutomationTemplate>(`/automations/templates/${id}`),
  saveTemplate: (id, payload) =>
    apiRequest<AutomationTemplate>(`/automations/templates/${id}`, {
      method: 'PUT',
      body: payload,
    }),
  deleteTemplate: (id) => apiRequest<void>(`/automations/templates/${id}`, { method: 'DELETE' }),

  startRecording: (payload) =>
    apiRequest<AutomationRecording>('/automations/recordings', { method: 'POST', body: payload }),
  getRecording: (id) => apiRequest<AutomationRecording>(`/automations/recordings/${id}`),
  stopRecording: (id) =>
    apiRequest<AutomationTemplate>(`/automations/recordings/${id}/stop`, { method: 'POST' }),
  cancelRecording: (id) =>
    apiRequest<void>(`/automations/recordings/${id}/cancel`, { method: 'POST' }),

  startRun: (templateId, payload) =>
    apiRequest<AutomationRun>(`/automations/templates/${templateId}/runs`, {
      method: 'POST',
      body: payload,
    }),
  getRun: (id) => apiRequest<AutomationRun>(`/automations/runs/${id}`),
  cancelRun: (id) =>
    apiRequest<AutomationRun>(`/automations/runs/${id}/cancel`, { method: 'POST' }),
  continueRunProfile: (runId, profileId) =>
    apiRequest<AutomationRun>(`/automations/runs/${runId}/profiles/${profileId}/continue`, {
      method: 'POST',
    }),
  retryRunProfile: (runId, profileId) =>
    apiRequest<AutomationRun>(`/automations/runs/${runId}/profiles/${profileId}/retry`, {
      method: 'POST',
    }),
  markRunProfileCompleted: (runId, profileId) =>
    apiRequest<AutomationRun>(`/automations/runs/${runId}/profiles/${profileId}/mark-completed`, {
      method: 'POST',
    }),

  getCredentialPool: () => apiRequest<CredentialPoolSummary>('/automations/credentials'),
  importCredentials: (text) =>
    apiRequest<CredentialPoolSummary>('/automations/credentials/import', {
      method: 'POST',
      body: { text },
    }),

  listFactoryJobs: () => apiRequest<ProfileFactoryJob[]>('/automations/factory/jobs'),
  startFactoryJob: (payload) =>
    apiRequest<ProfileFactoryJob>('/automations/factory/jobs', { method: 'POST', body: payload }),
  getFactoryJob: (id) => apiRequest<ProfileFactoryJob>(`/automations/factory/jobs/${id}`),
  cancelFactoryJob: (id) =>
    apiRequest<ProfileFactoryJob>(`/automations/factory/jobs/${id}/cancel`, { method: 'POST' }),

  listStores: () => apiRequest<ShopifyStore[]>('/shopify-builder/stores'),
  connectStore: (payload) =>
    apiRequest<ShopifyStore>('/shopify-builder/stores/connect', { method: 'POST', body: payload }),
  inspectStore: (id) =>
    apiRequest<ShopifyStore>(`/shopify-builder/stores/${id}/inspect`, { method: 'POST' }),
  setStoreNetworkRoute: (id, proxyId) =>
    apiRequest<ShopifyStore>(`/shopify-builder/stores/${id}/network-route`, {
      method: 'PUT',
      body: { proxy_id: proxyId },
    }),
  deleteStore: (id) => apiRequest<void>(`/shopify-builder/stores/${id}`, { method: 'DELETE' }),
  getStoreProfile: (id) => apiRequest<StoreProfile>(`/shopify-builder/stores/${id}/profile`),
  updateStoreProfile: (id, patch) =>
    apiRequest<StoreProfile>(`/shopify-builder/stores/${id}/profile`, {
      method: 'PUT',
      body: patch,
    }),

  getAiSettings: () => apiRequest<AiImageSettings>('/shopify-builder/ai-images/settings'),
  updateAiSettings: (patch) =>
    apiRequest<AiImageSettings>('/shopify-builder/ai-images/settings', {
      method: 'PUT',
      body: patch,
    }),

  getThemeLibrary: (storeId) =>
    apiRequest<ThemeLibrary>(`/shopify-builder/stores/${storeId}/themes/library`),
  inspectProductCsv: (storeId, content) =>
    apiRequest<ProductCsvInspection>(`/shopify-builder/stores/${storeId}/product-csv/inspect`, {
      method: 'POST',
      body: { content },
    }),
  listCatalogs: () => apiRequest<ProductCatalog[]>('/shopify-builder/catalogs'),

  createBuildPlan: (storeId, payload) =>
    apiRequest<BuildPlan>(`/shopify-builder/stores/${storeId}/plans`, {
      method: 'POST',
      body: payload,
    }),
  getBuildPlan: (storeId, planId) =>
    apiRequest<BuildPlan>(`/shopify-builder/stores/${storeId}/plans/${planId}`),
  executeBuildPlan: (storeId, planId, confirm) =>
    apiRequest<BuildPlan>(`/shopify-builder/stores/${storeId}/plans/${planId}/execute`, {
      method: 'POST',
      body: { confirm },
    }),

  listSessions: (limit) =>
    apiRequest<RuntimeSessionRecord[]>(`/sessions${limit ? `?limit=${limit}` : ''}`),

  listBackups: () => apiRequest<BackupArchive[]>('/backups'),
  createBackup: () => apiRequest<BackupArchive>('/backups', { method: 'POST' }),
  restoreBackup: (id) => apiRequest<void>(`/backups/${id}/restore`, { method: 'POST' }),
  deleteBackup: (id) => apiRequest<void>(`/backups/${id}`, { method: 'DELETE' }),

  getMediaSettings: () => apiRequest<MediaSettings>('/media/settings'),
  updateMediaSettings: (patch) =>
    apiRequest<MediaSettings>('/media/settings', { method: 'PATCH', body: patch }),
  listMediaAssets: () => apiRequest<MediaAsset[]>('/media/assets'),
  createMediaAsset: (payload) =>
    apiRequest<MediaAsset>('/media/assets', { method: 'POST', body: payload }),
  deleteMediaAsset: (id) => apiRequest<void>(`/media/assets/${id}`, { method: 'DELETE' }),
  getMediaAssignments: (assetId) => apiRequest<string[]>(`/media/assets/${assetId}/assignments`),
  setMediaAssignments: (assetId, profileIds) =>
    apiRequest<MediaAsset>(`/media/assets/${assetId}/assignments`, {
      method: 'PUT',
      body: { profile_ids: profileIds },
    }),

  listProxyProviders: () => apiRequest<ProxyProvider[]>('/proxies/providers'),
  configureProxyProvider: (payload) =>
    apiRequest<ProxyProvider>(`/proxies/providers/${payload.provider}`, {
      method: 'PUT',
      body: payload,
    }),
  generateProxies: (payload) =>
    apiRequest<GenerateProxiesResult>('/proxies/providers/generate', {
      method: 'POST',
      body: payload,
    }),
};
