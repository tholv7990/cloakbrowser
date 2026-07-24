/**
 * The API surface the whole app codes against. `realApi` (HTTP) and `mockApi`
 * (in-browser fixtures) both implement this, selected in api/index.ts by
 * VITE_API_MODE. UI/feature code imports `api` — never a concrete adapter.
 */
import type {
  AppBootstrap,
  AppVersion,
  AccountActivateRequest,
  AccountStatus,
  ArrangeRequest,
  ArrangeResponse,
  AuthStatus,
  LicenseStatus,
  AiImageSettings,
  AutomationRecording,
  AutomationRun,
  AutomationStep,
  AutomationTemplate,
  BackupArchive,
  BuildPlan,
  BulkProfileRequest,
  BulkProfileResult,
  ChangePasswordRequest,
  ConnectStorePayload,
  CookieImportPayload,
  CookieImportResult,
  CreateMediaAssetPayload,
  CreatePlanPayload,
  CredentialPoolSummary,
  DiagnosticRun,
  DiagnosticKind,
  DiagnosticListParams,
  DownloadFile,
  Extension,
  GenerateProxiesPayload,
  GenerateProxiesResult,
  MediaAsset,
  MediaSettings,
  Monitor,
  ProductCatalog,
  ProductCsvInspection,
  ProxyProvider,
  ProxyProviderConfigPayload,
  RuntimeSessionRecord,
  ShopifyStore,
  StartRunPayload,
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
  ProxyTestParams,
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

  // Cloud account + license (only enforced in licensed builds; 'disabled' otherwise)
  licenseStatus(): Promise<LicenseStatus>;
  accountStatus(): Promise<AccountStatus>;
  accountLogin(payload: EmailPasswordRequest): Promise<AccountStatus>;
  accountActivate(payload: AccountActivateRequest): Promise<LicenseStatus>;
  accountRegister(payload: EmailPasswordRequest): Promise<LicenseStatus>;
  accountRefresh(): Promise<LicenseStatus>;
  accountLogout(): Promise<AccountStatus>;

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
  getProfileLogs(id: string, params?: { page?: number; page_size?: number }): Promise<ProfileLogs>;
  getProfileLogTail(
    id: string,
    params?: { cursor?: string; limit?: number },
  ): Promise<ProfileLogTail>;
  exportProfile(id: string): Promise<DownloadFile>;
  importProfile(payload: Record<string, unknown>): Promise<ProfileImportResult>;
  importCookies(id: string, payload: CookieImportPayload): Promise<CookieImportResult>;
  exportCookies(id: string, format: 'playwright' | 'netscape'): Promise<DownloadFile>;
  openProfileDirectory(id: string): Promise<{ profile_directory: string }>;
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

  // Local unpacked extensions
  listExtensions(): Promise<Extension[]>;
  registerExtension(directory: string): Promise<Extension>;
  updateExtension(id: string, patch: { enabled?: boolean; refresh?: boolean }): Promise<Extension>;
  unregisterExtension(id: string): Promise<void>;
  getProfileExtensions(id: string): Promise<ProfileExtensionAssignment>;
  setProfileExtensions(id: string, extensionIds: string[]): Promise<ProfileExtensionAssignment>;

  // Proxies
  listProxies(): Promise<Proxy[]>;
  getProxy(id: string): Promise<Proxy>;
  createProxy(payload: ProxyWritePayload): Promise<Proxy>;
  updateProxy(id: string, payload: ProxyWritePayload): Promise<Proxy>;
  deleteProxy(id: string): Promise<{ ok: boolean }>;
  parseProxy(raw: string): Promise<ParsedProxy>;
  quickTestProxy(id: string): Promise<ProxyQuickTest>;
  quickTestProxyAdhoc(params: ProxyTestParams): Promise<ProxyQuickTest>;
  qualityTestProxy(id: string): Promise<ProxyQualityReport>;
  getProxyReports(id: string): Promise<ProxyQualityReport[]>;

  // Diagnostics / settings
  listDiagnostics(params?: DiagnosticListParams): Promise<Paginated<DiagnosticRun>>;
  getDiagnostic(id: string): Promise<DiagnosticRun>;
  runDirectGoogleControl(): Promise<DiagnosticRun>;
  runPixelscan(profileId: string): Promise<DiagnosticRun>;
  runDiagnostic(
    kind: Exclude<DiagnosticKind, 'direct_google_control'>,
    profileId: string,
  ): Promise<DiagnosticRun>;
  cancelDiagnostic(id: string): Promise<DiagnosticRun>;
  getSettings(): Promise<Settings>;
  updateSettings(patch: Partial<Settings>): Promise<Settings>;
  checkBrowserUpdate(): Promise<Settings>;

  // Resource monitor (read-only)
  getResources(): Promise<ResourceSnapshot>;

  // Automation — templates / recordings / runs / credentials / factory
  listTemplates(): Promise<AutomationTemplate[]>;
  getTemplate(id: string): Promise<AutomationTemplate>;
  saveTemplate(
    id: string,
    payload: { name: string; description: string; steps: AutomationStep[] },
  ): Promise<AutomationTemplate>;
  deleteTemplate(id: string): Promise<void>;

  startRecording(payload: {
    name: string;
    profile_id: string;
    description: string;
  }): Promise<AutomationRecording>;
  getRecording(id: string): Promise<AutomationRecording>;
  stopRecording(id: string): Promise<AutomationTemplate>;
  cancelRecording(id: string): Promise<void>;

  startRun(templateId: string, payload: StartRunPayload): Promise<AutomationRun>;
  getRun(id: string): Promise<AutomationRun>;
  cancelRun(id: string): Promise<AutomationRun>;
  continueRunProfile(runId: string, profileId: string): Promise<AutomationRun>;
  retryRunProfile(runId: string, profileId: string): Promise<AutomationRun>;
  markRunProfileCompleted(runId: string, profileId: string): Promise<AutomationRun>;

  getCredentialPool(): Promise<CredentialPoolSummary>;
  importCredentials(text: string): Promise<CredentialPoolSummary>;


  // Shopify Builder — stores / analysis / plans (draft-only)
  listStores(): Promise<ShopifyStore[]>;
  connectStore(payload: ConnectStorePayload): Promise<ShopifyStore>;
  inspectStore(id: string): Promise<ShopifyStore>;
  setStoreNetworkRoute(id: string, proxyId: string | null): Promise<ShopifyStore>;
  deleteStore(id: string): Promise<void>;
  getStoreProfile(id: string): Promise<StoreProfile>;
  updateStoreProfile(id: string, patch: Partial<StoreProfile>): Promise<StoreProfile>;

  getAiSettings(): Promise<AiImageSettings>;
  updateAiSettings(
    patch: Partial<AiImageSettings> & { api_key?: string },
  ): Promise<AiImageSettings>;

  getThemeLibrary(storeId: string): Promise<ThemeLibrary>;
  inspectProductCsv(storeId: string, content: string): Promise<ProductCsvInspection>;
  listCatalogs(): Promise<ProductCatalog[]>;

  createBuildPlan(storeId: string, payload: CreatePlanPayload): Promise<BuildPlan>;
  getBuildPlan(storeId: string, planId: string): Promise<BuildPlan>;
  executeBuildPlan(storeId: string, planId: string, confirm: boolean): Promise<BuildPlan>;

  // Session history (read-only)
  listSessions(limit?: number): Promise<RuntimeSessionRecord[]>;

  // Window arrangement (Synchronize page) — Windows-only, inert elsewhere
  getMonitors(): Promise<Monitor[]>;
  arrangeWindows(payload: ArrangeRequest): Promise<ArrangeResponse>;

  // Backups
  listBackups(): Promise<BackupArchive[]>;
  createBackup(): Promise<BackupArchive>;
  restoreBackup(id: string): Promise<void>;
  deleteBackup(id: string): Promise<void>;

  // Media engine
  getMediaSettings(): Promise<MediaSettings>;
  updateMediaSettings(patch: Partial<MediaSettings>): Promise<MediaSettings>;
  listMediaAssets(): Promise<MediaAsset[]>;
  createMediaAsset(payload: CreateMediaAssetPayload): Promise<MediaAsset>;
  deleteMediaAsset(id: string): Promise<void>;
  getMediaAssignments(assetId: string): Promise<string[]>;
  setMediaAssignments(assetId: string, profileIds: string[]): Promise<MediaAsset>;

  // Proxy providers (IPRoyal / 711Proxy)
  listProxyProviders(): Promise<ProxyProvider[]>;
  configureProxyProvider(payload: ProxyProviderConfigPayload): Promise<ProxyProvider>;
  generateProxies(payload: GenerateProxiesPayload): Promise<GenerateProxiesResult>;
}
