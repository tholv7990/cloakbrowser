/**
 * Typed REST contract for the CloakBrowser Manager backend.
 *
 * Reconciled against the authoritative Pydantic schemas on the
 * `feature/manager-backend` branch (manager_backend/features/profiles/schemas.py,
 * schemas/common.py, auth/schemas.py, features/catalog/schemas.py) and the
 * updated design spec §3/§7/§12/§13. The backend uses `extra="forbid"`, so write
 * payloads must match these shapes exactly.
 *
 * No type here carries a proxy password, auth header, cookie value, session
 * token, or website credential — those never cross the API by contract (§3).
 */

// ---------------------------------------------------------------------------
// Enums / unions
// ---------------------------------------------------------------------------

export type FingerprintPreset = 'default' | 'consistent';

/** Backend runtime_state enum (no `unreachable`; that is a reconciliation state). */
export type RuntimeState = 'stopped' | 'starting' | 'running' | 'stopping' | 'crashed';

export type ProxyScheme = 'direct' | 'http' | 'https' | 'socks5' | 'socks5h';
export type ProxyType = 'residential' | 'datacenter' | 'mobile' | 'isp' | 'hosting' | 'unknown';
export type ProxyReputation = 'clean' | 'neutral' | 'suspicious' | 'malicious' | 'unknown';
export type ProxyHealth = 'healthy' | 'degraded' | 'unreachable' | 'untested' | 'unknown';

export type GeoMode = 'proxy' | 'manual' | 'system';
export type WebRtcMode = 'proxy' | 'direct' | 'disabled';
export type GeolocationMode = 'proxy' | 'manual' | 'ask' | 'block';
export type WindowMode = 'maximized' | 'custom';
export type ColorScheme = 'system' | 'light' | 'dark';
export type BrowserVersionMode = 'installed' | 'pinned';
export type UserAgentMode = 'automatic' | 'custom';
export type HumanizePreset = 'default' | 'careful';
export type DownloadDirMode = 'profile' | 'custom';
export type HardwareConcurrencyMode = 'automatic' | 'custom';
export type GpuMode = 'automatic' | 'custom_vendor';
export type PermissionSetting = 'ask' | 'allow' | 'block';
export type CookieFormat = 'netscape' | 'json' | 'playwright';

// ---------------------------------------------------------------------------
// Catalog value objects
// ---------------------------------------------------------------------------

export interface Tag {
  id: string;
  name: string;
  color: string;
}

export interface Folder {
  id: string;
  name: string;
  position: number;
  created_at: string;
  updated_at: string;
  /** Not part of FolderRead; supplied by bootstrap/derivation where available. */
  profile_count?: number;
  running_count?: number;
}

export interface WorkflowStatus {
  id: string;
  name: string;
  color: string;
  position: number;
}

export interface Extension {
  id: string;
  name: string;
  path: string;
  manifest_version: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface BrowserInfo {
  name: string;
  version: string;
  chromium_version: string;
  path_present: boolean;
}

// ---------------------------------------------------------------------------
// Proxy (unchanged contract). Responses never contain `password`.
// ---------------------------------------------------------------------------

export interface Proxy {
  id: string;
  label: string;
  scheme: ProxyScheme;
  host: string;
  port: number | null;
  username: string | null;
  has_password: boolean;
  masked_endpoint: string;
  test_before_launch: boolean;
  assigned_profile_count: number;
  exit_ip: string | null;
  country: string | null;
  city: string | null;
  timezone: string | null;
  asn: string | null;
  organization: string | null;
  proxy_type: ProxyType | null;
  type_confidence: number | null;
  reputation: ProxyReputation | null;
  latency_ms: number | null;
  last_checked_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ParsedProxy {
  scheme: ProxyScheme;
  host: string;
  port: number | null;
  username: string | null;
  has_password: boolean;
}

export interface AlignmentFinding {
  status: 'aligned' | 'mismatch' | 'leak' | 'unknown';
  detail: string;
}

export interface ProxyQuickTest {
  ok: boolean;
  connectivity: boolean;
  exit_ip: string | null;
  exit_ip_matches: boolean | null;
  latency_ms: number | null;
  country: string | null;
  country_name: string | null;
  city: string | null;
  timezone: string | null;
  latitude: number | null;
  longitude: number | null;
  zip_code: string | null;
  asn: string | null;
  organization: string | null;
  checked_at: string;
  error: string | null;
}

export interface ProxyQualityReport {
  id: string;
  proxy_id: string;
  state: 'queued' | 'running' | 'completed' | 'failed';
  proxy_type: ProxyType | null;
  type_confidence: number | null;
  reputation: ProxyReputation | null;
  matched_lists: string[];
  google_outcome: 'passed' | 'captcha' | 'blocked' | 'unknown' | null;
  turnstile_outcome: 'passed' | 'challenge' | 'failed' | 'unknown' | null;
  alignment: {
    http: AlignmentFinding;
    webrtc: AlignmentFinding;
    dns: AlignmentFinding;
    timezone: AlignmentFinding;
    locale: AlignmentFinding;
  };
  latency_ms: number | null;
  exit_ip: string | null;
  country: string | null;
  city: string | null;
  timezone: string | null;
  asn: string | null;
  organization: string | null;
  screenshot_path: string | null;
  report_path: string | null;
  observed_scope: string;
  checked_at: string;
}

// ---------------------------------------------------------------------------
// Profile — grouped settings (LocationSettings / WindowSettings / BehaviorSettings)
// ---------------------------------------------------------------------------

export interface LocationSettings {
  geo_mode: GeoMode;
  locale: string | null;
  timezone: string | null;
  webrtc_mode: WebRtcMode;
  geolocation_mode: GeolocationMode;
  latitude: number | null;
  longitude: number | null;
  accuracy: number | null;
}

export interface WindowSettings {
  mode: WindowMode;
  width: number | null;
  height: number | null;
  color_scheme: ColorScheme;
}

export interface BehaviorSettings {
  humanize_enabled: boolean;
  humanize_preset: HumanizePreset;
  clear_cache_before_launch: boolean;
  restore_previous_tabs: boolean;
  download_directory_mode: DownloadDirMode;
  custom_download_directory: string | null;
  permissions: Record<string, PermissionSetting>;
  ignore_https_errors: boolean;
  hardware_concurrency_mode: HardwareConcurrencyMode;
  hardware_concurrency: number | null;
  gpu_mode: GpuMode;
  gpu_vendor: string | null;
  additional_args: string[];
}

/** ProfileCreate / ProfilePatch body. Patch replaces the whole profile, so the
 * frontend always sends the full object on update. */
export interface ProfileWrite {
  name: string;
  folder_id: string | null;
  workflow_status_id: string | null;
  tag_ids: string[];
  notes: string;
  pinned: boolean;
  startup_urls: string[];
  fingerprint_seed: string | null;
  fingerprint_preset: FingerprintPreset;
  browser_version_mode: BrowserVersionMode;
  browser_version: string | null;
  user_agent_mode: UserAgentMode;
  custom_user_agent: string | null;
  location: LocationSettings;
  window: WindowSettings;
  behavior: BehaviorSettings;
  proxy_id: string | null;
  test_proxy_before_launch: boolean;
}

export type ProfileCreatePayload = ProfileWrite;
export type ProfileUpdatePayload = ProfileWrite;

/** ProfileRead — the single profile shape returned for list and detail. */
export interface ProfileRead extends ProfileWrite {
  id: string;
  fingerprint_seed: string;
  fingerprint_revision: number;
  fingerprint_config_hash: string;
  runtime_state: RuntimeState;
  created_at: string;
  updated_at: string;
  last_opened_at: string | null;
  total_runtime_seconds: number;
  deleted_at: string | null;
}

/**
 * Enriched view model built client-side by joining ProfileRead against the
 * catalog (tags/statuses/proxies) and a realtime message overlay. The wire
 * object stays available as `read` for the editor and row actions.
 */
export interface ProfileView {
  id: string;
  name: string;
  pinned: boolean;
  folder_id: string | null;
  fingerprint_seed: string;
  tags: Tag[];
  notes: string;
  workflow_status: WorkflowStatus | null;
  proxy: Proxy | null;
  runtime_state: RuntimeState;
  runtime_message: string | null;
  last_opened_at: string | null;
  browser_version_mode: BrowserVersionMode;
  browser_version: string | null;
  read: ProfileRead;
}

// ---------------------------------------------------------------------------
// Requests
// ---------------------------------------------------------------------------

export type ProfileSort =
  | 'name'
  | '-name'
  | 'updated_at'
  | '-updated_at'
  | 'created_at'
  | '-created_at'
  | 'last_opened_at'
  | '-last_opened_at';

export interface ProfileListParams {
  query?: string;
  folder_id?: string | null;
  tag_id?: string;
  workflow_status_id?: string;
  pinned?: boolean;
  sort?: ProfileSort;
  page?: number;
  page_size?: number;
}

export interface BulkProfileRequest {
  action: 'trash' | 'restore' | 'pin' | 'unpin' | 'move_folder' | 'set_status';
  ids: string[];
  folder_id?: string | null;
  workflow_status_id?: string | null;
}

export interface BulkProfileResult {
  updated_ids: string[];
  count: number;
}

export interface ProxyWritePayload {
  label: string;
  scheme: ProxyScheme;
  host: string;
  port: number | null;
  username: string | null;
  /** Write-only. Present only on create/update; never returned. */
  password?: string | null;
  test_before_launch: boolean;
}

export interface CookieImportPayload {
  format: CookieFormat;
  content: string;
}

export interface CookieImportResult {
  imported_count: number;
  skipped_count: number;
  format: CookieFormat;
  warnings: string[];
}

// ---------------------------------------------------------------------------
// Auth (spec §3, §13). Local owner account; session lives in an HttpOnly cookie.
// ---------------------------------------------------------------------------

export interface AuthStatus {
  setup_required: boolean;
}

export interface OwnerSession {
  email: string;
  csrf_token: string;
}

export interface EmailPasswordRequest {
  email: string;
  password: string;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

// ---------------------------------------------------------------------------
// Application / bootstrap / settings
// ---------------------------------------------------------------------------

export interface AppVersion {
  manager_api_version: string;
  cloakbrowser_version: string;
  chromium_version: string;
}

export interface AppCapabilities {
  authentication: boolean;
  profiles: boolean;
  catalogs: boolean;
  proxy_management: boolean;
  browser_runtime: boolean;
  fingerprint_diagnostics: boolean;
  settings: boolean;
  /** Optional — present once the Automation backend ships. Treated as false when absent. */
  automation?: boolean;
  /** Optional — present once the Shopify Builder backend ships. Treated as false when absent. */
  shopify_builder?: boolean;
  /** Optional — present once the media engine backend ships. Treated as false when absent. */
  media?: boolean;
}

export interface Settings {
  profile_root: string;
  report_root: string;
  default_locale: string;
  default_timezone: string;
  default_test_before_launch: boolean;
  rows_per_page: number;
  theme: 'light' | 'dark' | 'system';
  log_retention_days: number;
  trash_retention_days: number;
  browser: {
    name: string;
    version: string;
    path: string;
    platform: string;
    tier: 'free' | 'pro';
    installed: boolean;
    update_available: boolean;
    latest_version: string | null;
  };
  license: {
    configured: boolean;
    valid: boolean | null;
    plan: string | null;
    expires: string | null;
    active_sessions: number | null;
    session_limit: number | null;
  };
}

/** Canonical GET /app/bootstrap — minimal app info + feature flags (not the catalog). */
export interface AppBootstrap {
  api_version: string;
  platform: string;
  owner_email: string;
  capabilities: AppCapabilities;
}

// ---------------------------------------------------------------------------
// Resource monitor (GET /resources) — read-only per-profile CPU/RAM sampling.
// Observability only: the backend never caps, prioritizes, or allocates.
// ---------------------------------------------------------------------------

export interface SystemResources {
  cpu_percent: number;
  memory_percent: number;
  memory_used_bytes: number;
  memory_total_bytes: number;
  logical_cpus: number;
}

/** Aggregate usage for a group of OS processes (CPU is 0–100, already ÷ cores). */
export interface ProcessGroupResources {
  cpu_percent: number;
  memory_bytes: number;
  process_count: number;
}

export interface ProfileResourceRow extends ProcessGroupResources {
  profile_id: string;
  profile_name: string;
  runtime_state: RuntimeState;
}

export interface ResourceSnapshot {
  generated_at: string;
  system: SystemResources;
  backend: ProcessGroupResources;
  browsers: ProcessGroupResources & { profiles_running: number };
  /** Only running profiles, sorted heaviest-first by the backend. */
  profiles: ProfileResourceRow[];
}

// ---------------------------------------------------------------------------
// Automation — record a flow, save it as a template, replay across profiles.
// Contract: docs/backend-contract-automation.md. No step value ever holds a
// website credential — email/password are variable references.
// ---------------------------------------------------------------------------

export type AutomationStepType = 'goto' | 'click' | 'fill' | 'select' | 'wait_url';

/** Ordered locator strategies; replay tries them in order (stable id/name for
 * fields, role + accessible name for clicks). */
export interface AutomationSelector {
  css?: string;
  id?: string;
  name?: string;
  role?: string;
  accessible_name?: string;
  placeholder?: string;
  aria_label?: string;
  text?: string;
  testid?: string;
}

export interface AutomationStep {
  type: AutomationStepType;
  url?: string;
  url_pattern?: string;
  success_url_pattern?: string;
  selectors?: AutomationSelector[];
  /** A literal value, OR a variable ref via `variable`. Credentials are never literals. */
  value?: string | null;
  variable?: string | null;
}

export interface AutomationTemplate {
  id: string;
  name: string;
  description: string;
  steps: AutomationStep[];
  /** Variable names the template needs at run time, e.g. ['email','password']. */
  variables: string[];
  created_at: string;
  updated_at: string;
}

export type RecordingStatus = 'recording' | 'stopped' | 'cancelled';

export interface AutomationRecording {
  id: string;
  name: string;
  description: string;
  profile_id: string;
  status: RecordingStatus;
  step_count: number;
  /** Set once stopped and converted to a template. */
  template_id: string | null;
  created_at: string;
}

export type RunItemStatus =
  | 'pending'
  | 'running'
  | 'attention'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface AutomationRunItem {
  profile_id: string;
  profile_name: string;
  status: RunItemStatus;
  current_step: number;
  total_steps: number;
  last_completed_step: number;
  message: string | null;
  /** Human-readable gate reason when status is 'attention' (CAPTCHA/OTP/…). */
  attention_reason: string | null;
  error: string | null;
}

export type RunStatus = 'running' | 'completed' | 'failed' | 'cancelled';

export interface AutomationRun {
  id: string;
  template_id: string;
  template_name: string;
  status: RunStatus;
  max_parallel: number;
  total: number;
  completed_count: number;
  failed_count: number;
  attention_count: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  items: AutomationRunItem[];
}

export interface AutomationRunAssignment {
  profile_id: string;
  variables: Record<string, string>;
  credential_id?: string | null;
}

export interface StartRunPayload {
  assignments: AutomationRunAssignment[];
  max_parallel: number;
}

/** Pool counts only — never the credentials themselves. */
export interface CredentialPoolSummary {
  available: number;
  reserved: number;
  used: number;
  failed: number;
  total: number;
}

export type FactoryJobStatus = 'running' | 'completed' | 'failed' | 'cancelled';

export interface ProfileFactoryItem {
  id: string;
  profile_id: string | null;
  status: string;
  message: string | null;
}

export interface ProfileFactoryJob {
  id: string;
  status: FactoryJobStatus;
  quantity: number;
  name_prefix: string;
  automation_template_id: string | null;
  start_automation: boolean;
  created_count: number;
  failed_count: number;
  items: ProfileFactoryItem[];
  created_at: string;
}

export interface StartFactoryPayload {
  quantity: number;
  name_prefix: string;
  automation_template_id?: string | null;
  start_automation: boolean;
}

// ---------------------------------------------------------------------------
// Shopify Builder — connect a store, analyze, stage a plan, execute as drafts.
// Contract: docs/backend-contract-shopify-builder.md. Draft-only: nothing is
// ever published, and secrets (client id/secret, token, AI key) never return.
// ---------------------------------------------------------------------------

export type StoreCapabilityKey =
  | 'write_products'
  | 'write_pages'
  | 'write_legal_policies'
  | 'write_navigation'
  | 'write_themes';

export interface ShopifyStore {
  id: string;
  label: string;
  shop_domain: string;
  connected: boolean;
  scopes: string[];
  capabilities: Record<StoreCapabilityKey, boolean>;
  shop_name: string | null;
  product_count: number | null;
  proxy_id: string | null;
  exit_ip: string | null;
  niche: string | null;
  language: string | null;
  created_at: string;
  updated_at: string;
}

export interface StoreProfile {
  niche: string | null;
  language: string | null;
  store_name: string;
  support_email: string;
}

/** AI image generation settings. `has_api_key` only — the key never returns. */
export interface AiImageSettings {
  enabled: boolean;
  provider: string;
  model: string;
  has_api_key: boolean;
}

export interface ThemeInfo {
  id: string;
  name: string;
  role: 'main' | 'unpublished' | 'demo';
  presets: string[];
}

export interface ThemeLibrary {
  integrated: ThemeInfo[];
  store: ThemeInfo[];
}

export interface ProductRow {
  handle: string;
  title: string;
  price: string;
  variants: number;
}

export interface ProductCsvInspection {
  total: number;
  sample: ProductRow[];
  columns_mapped: string[];
  columns_unmapped: string[];
}

export interface ProductCatalog {
  id: string;
  name: string;
  niche: string;
  product_count: number;
}

export type PlanStepStatus = 'planned' | 'ready' | 'blocked' | 'running' | 'completed' | 'failed';

export interface PlanStep {
  key: string;
  status: PlanStepStatus;
  reason: string | null;
  error: string | null;
}

export type BuildPlanStatus = 'staged' | 'running' | 'completed' | 'partial' | 'failed';

export interface BuildPlan {
  id: string;
  store_id: string;
  status: BuildPlanStatus;
  mode: 'draft_only';
  niche: string;
  language: string;
  theme_name: string;
  preset: string;
  product_count: number;
  ai_hero: boolean;
  steps: PlanStep[];
  admin_url: string | null;
  preview_url: string | null;
  created_at: string;
}

export interface ConnectStorePayload {
  label: string;
  shop_domain: string;
  client_id: string;
  client_secret: string;
  proxy_id?: string | null;
}

export interface CreatePlanPayload {
  theme_id: string;
  preset: string;
  product_source: 'catalog' | 'csv';
  catalog_id?: string | null;
  niche_override?: string | null;
  ai_hero: boolean;
}

// ---------------------------------------------------------------------------
// Session history — one record per profile launch (read-only).
// ---------------------------------------------------------------------------

export type SessionExitReason = 'closed' | 'stopped' | 'crashed' | 'timeout' | 'unknown';

export interface RuntimeSessionRecord {
  id: string;
  profile_id: string;
  profile_name: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  startup_ms: number | null;
  exit_reason: SessionExitReason | null;
}

// ---------------------------------------------------------------------------
// Backups — verified local snapshots of manager metadata (never browser data).
// ---------------------------------------------------------------------------

export interface BackupArchive {
  id: string;
  created_at: string;
  size_bytes: number;
  automatic: boolean;
  verified: boolean;
  /** e.g. ['profiles','proxies','workspaces','extensions']. */
  contents: string[];
}

// ---------------------------------------------------------------------------
// Media engine — virtual camera/mic/screen assets injected into profiles.
// ---------------------------------------------------------------------------

export type MediaKind = 'camera' | 'microphone' | 'screen';

export interface MediaAsset {
  id: string;
  name: string;
  kind: MediaKind;
  /** MIME type, e.g. 'image/jpeg', 'video/mp4', 'audio/wav'. */
  format: string;
  size_bytes: number;
  assigned_profile_count: number;
  created_at: string;
}

export interface MediaSettings {
  enabled: boolean;
}

export interface CreateMediaAssetPayload {
  name: string;
  kind: MediaKind;
  format: string;
}

// ---------------------------------------------------------------------------
// Proxy providers — connect IPRoyal / 711Proxy and generate proxies into the
// pool. Credentials are stored securely and never returned.
// ---------------------------------------------------------------------------

export type ProxyProviderId = 'iproyal' | 'seveneleven';

export interface ProxyProvider {
  id: ProxyProviderId;
  name: string;
  configured: boolean;
}

export interface ProxyProviderConfigPayload {
  provider: ProxyProviderId;
  /** IPRoyal. */
  api_token?: string;
  /** 711Proxy. */
  username?: string;
  password?: string;
}

export interface GenerateProxiesPayload {
  provider: ProxyProviderId;
  count: number;
  country: string;
  session_type: 'rotating' | 'sticky';
}

export interface GenerateProxiesResult {
  created: number;
  proxy_ids: string[];
}

// ---------------------------------------------------------------------------
// Diagnostics + logs
// ---------------------------------------------------------------------------

export type DiagnosticKind =
  | 'proxy_quality'
  | 'pixelscan'
  | 'direct_google_control'
  | 'launch_failure'
  | 'fingerprint_verification';

export interface DiagnosticRun {
  id: string;
  kind: DiagnosticKind;
  proxy_id: string | null;
  profile_id: string | null;
  state: 'queued' | 'running' | 'completed' | 'failed';
  summary: string;
  artifact_path: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProfileLogEntry {
  timestamp: string;
  level: 'debug' | 'info' | 'warning' | 'error';
  message: string;
}

export interface ProfileLogs {
  profile_id: string;
  entries: ProfileLogEntry[];
}

// ---------------------------------------------------------------------------
// Envelopes
// ---------------------------------------------------------------------------

/** Backend Page: note `pages` (not `total_pages`). */
export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    field_errors: Record<string, string[]>;
    request_id: string;
  };
}
