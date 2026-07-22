/**
 * The API surface the whole app codes against. `realApi` (HTTP) and `mockApi`
 * (in-browser fixtures) both implement this, selected in api/index.ts by
 * VITE_API_MODE. UI/feature code imports `api` — never a concrete adapter.
 */
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
  ResourceSnapshot,
  Settings,
  Tag,
  WorkflowStatus,
} from '@/types/api';

export interface ApiAdapter {
  readonly mode: 'mock' | 'real';

  // Auth (local owner account; session lives in an HttpOnly cookie)
  authStatus(): Promise<AuthStatus>;
  authSetup(payload: EmailPasswordRequest): Promise<OwnerSession>;
  authLogin(payload: EmailPasswordRequest): Promise<OwnerSession>;
  authSession(): Promise<OwnerSession>;
  authLogout(): Promise<{ ok: boolean }>;
  authLock(): Promise<{ ok: boolean }>;
  authChangePassword(payload: ChangePasswordRequest): Promise<{ ok: boolean }>;

  // Application
  health(): Promise<{ ok: boolean }>;
  bootstrap(): Promise<AppBootstrap>;
  version(): Promise<AppVersion>;

  // Profiles
  listProfiles(params: ProfileListParams): Promise<Paginated<ProfileRead>>;
  getProfile(id: string): Promise<ProfileRead>;
  createProfile(payload: ProfileCreatePayload): Promise<ProfileRead>;
  quickCreateProfile(payload: ProfileCreatePayload): Promise<ProfileRead>;
  updateProfile(id: string, payload: ProfileUpdatePayload): Promise<ProfileRead>;
  duplicateProfile(id: string): Promise<ProfileRead>;
  regenerateFingerprint(id: string): Promise<ProfileRead>;
  // Start/stop return a runtime session (202); the row state arrives via the
  // runtime snapshot / refetch, so callers treat these as fire-and-forget.
  startProfile(id: string): Promise<void>;
  stopProfile(id: string): Promise<void>;
  focusWindow(id: string): Promise<{ ok: boolean }>;
  moveProfileToTrash(id: string): Promise<{ ok: boolean }>;
  restoreProfile(id: string): Promise<ProfileRead>;
  getProfileLogs(id: string): Promise<ProfileLogs>;
  exportProfile(id: string): Promise<Record<string, unknown>>;
  importProfile(payload: Record<string, unknown>): Promise<ProfileRead>;
  importCookies(id: string, payload: CookieImportPayload): Promise<CookieImportResult>;
  bulkProfiles(request: BulkProfileRequest): Promise<BulkProfileResult>;

  // Folders / tags / statuses
  listFolders(): Promise<Folder[]>;
  createFolder(name: string): Promise<Folder>;
  renameFolder(id: string, name: string): Promise<Folder>;
  reorderFolders(orderedIds: string[]): Promise<Folder[]>;
  deleteFolder(id: string): Promise<{ ok: boolean }>;
  listTags(): Promise<Tag[]>;
  createTag(payload: { name: string; color?: string }): Promise<Tag>;
  listWorkflowStatuses(): Promise<WorkflowStatus[]>;

  // Proxies
  listProxies(): Promise<Proxy[]>;
  getProxy(id: string): Promise<Proxy>;
  createProxy(payload: ProxyWritePayload): Promise<Proxy>;
  updateProxy(id: string, payload: ProxyWritePayload): Promise<Proxy>;
  deleteProxy(id: string): Promise<{ ok: boolean }>;
  parseProxy(raw: string): Promise<ParsedProxy>;
  quickTestProxy(id: string): Promise<ProxyQuickTest>;
  qualityTestProxy(id: string): Promise<ProxyQualityReport>;
  getProxyReports(id: string): Promise<ProxyQualityReport[]>;

  // Diagnostics / settings
  listDiagnostics(): Promise<DiagnosticRun[]>;
  getDiagnostic(id: string): Promise<DiagnosticRun>;
  runDirectGoogleControl(): Promise<DiagnosticRun>;
  runPixelscan(profileId: string): Promise<DiagnosticRun>;
  getSettings(): Promise<Settings>;
  updateSettings(patch: Partial<Settings>): Promise<Settings>;
  checkBrowserUpdate(): Promise<Settings>;

  // Resource monitor (read-only)
  getResources(): Promise<ResourceSnapshot>;
}
