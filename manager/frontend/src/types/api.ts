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
  city: string | null;
  timezone: string | null;
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
