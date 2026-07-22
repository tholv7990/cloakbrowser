/** Mock backend adapter. Fully exercises the UI without a live server. */
import type {
  AppBootstrap,
  AppVersion,
  AuthStatus,
  AiImageSettings,
  AutomationRecording,
  AutomationRun,
  AutomationRunItem,
  AutomationStep,
  AutomationTemplate,
  BackupArchive,
  BuildPlan,
  BulkProfileRequest,
  BulkProfileResult,
  ChangePasswordRequest,
  CookieImportPayload,
  CookieImportResult,
  CredentialPoolSummary,
  DiagnosticKind,
  DiagnosticRun,
  Extension,
  GenerateProxiesResult,
  MediaAsset,
  MediaSettings,
  PlanStep,
  ProductCatalog,
  ProductCsvInspection,
  ProductRow,
  ProfileFactoryItem,
  ProfileFactoryJob,
  ProxyProvider,
  RuntimeSessionRecord,
  SessionExitReason,
  ShopifyStore,
  StoreCapabilityKey,
  StoreProfile,
  ThemeInfo,
  ThemeLibrary,
  EmailPasswordRequest,
  Folder,
  OwnerSession,
  Paginated,
  ParsedProxy,
  ProfileCreatePayload,
  ProfileListParams,
  ProfileLogs,
  ProfileLogTail,
  ProfileRead,
  ProfileUpdatePayload,
  Proxy,
  ProxyQualityReport,
  ProxyQuickTest,
  ProxyScheme,
  ProxyWritePayload,
  ResourceSnapshot,
  RuntimeState,
  Settings,
} from '@/types/api';
import { ApiError } from '@/api/http';
import type { ApiAdapter } from '@/api/adapter';
import { setCsrfToken } from '@/api/config';
import {
  defaultBehavior,
  defaultLocation,
  defaultWindow,
  fakeConfigHash,
  maskEndpoint,
  ownerEmail,
} from './data';
import { mockStore, newId } from './store';

const now = () => new Date().toISOString();
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const randomSeed = () => String(Math.floor(Math.random() * 2 ** 32));

// --- Automation mock state + time-based live simulation ----------------------
function sampleSteps(): AutomationStep[] {
  return [
    { type: 'goto', url: 'https://example.com/signup', url_pattern: 'https://example.com/signup' },
    { type: 'fill', selectors: [{ id: 'email', name: 'email' }], variable: 'email' },
    { type: 'fill', selectors: [{ id: 'password', name: 'password' }], variable: 'password' },
    {
      type: 'click',
      selectors: [{ role: 'button', accessible_name: 'Create account' }],
      success_url_pattern: 'https://example.com/welcome',
    },
    { type: 'wait_url', url_pattern: 'https://example.com/welcome' },
    { type: 'click', selectors: [{ text: 'Continue' }] },
  ];
}
function deriveVars(steps: AutomationStep[]): string[] {
  const set = new Set<string>();
  for (const step of steps) if (step.variable) set.add(step.variable);
  return [...set];
}

const mockTemplates: AutomationTemplate[] = [
  {
    id: 'tpl_demo_signup',
    name: 'Marketplace sign-up',
    description: 'Create an account and confirm the welcome page.',
    steps: sampleSteps(),
    variables: ['email', 'password'],
    created_at: now(),
    updated_at: now(),
  },
];
const mockRecordings: AutomationRecording[] = [];
const mockRuns: AutomationRun[] = [];
const mockFactoryJobs: ProfileFactoryJob[] = [];
let mockPool: CredentialPoolSummary = { available: 4, reserved: 0, used: 0, failed: 0, total: 4 };

/** gateProfile stalls at the midpoint until continued; failProfile fails at the end until retried. */
const runSim = new Map<
  string,
  { gateProfile: string | null; gatePassed: boolean; failProfile: string | null }
>();
const factoryStart = new Map<string, number>();
const TERMINAL: AutomationRunItem['status'][] = ['completed', 'failed', 'cancelled'];

function progressRecording(rec: AutomationRecording): void {
  if (rec.status !== 'recording') return;
  const elapsed = Date.now() - Date.parse(rec.created_at);
  rec.step_count = Math.min(8, Math.max(rec.step_count, Math.floor(elapsed / 1200)));
}
function recomputeRun(run: AutomationRun): void {
  run.completed_count = run.items.filter((i) => i.status === 'completed').length;
  run.failed_count = run.items.filter((i) => i.status === 'failed').length;
  run.attention_count = run.items.filter((i) => i.status === 'attention').length;
  const active = run.items.some((i) => !TERMINAL.includes(i.status));
  if (!active && run.status === 'running') {
    run.status = run.failed_count > 0 && run.completed_count === 0 ? 'failed' : 'completed';
    run.finished_at = now();
  }
}
function progressRun(run: AutomationRun): void {
  if (run.status !== 'running') return;
  const sim = runSim.get(run.id);
  const gateStep = Math.ceil((run.items[0]?.total_steps ?? 6) / 2);
  for (const item of run.items) {
    if (TERMINAL.includes(item.status) || item.status === 'attention') continue;
    if (item.status === 'pending') item.status = 'running';
    if (
      sim &&
      item.profile_id === sim.gateProfile &&
      !sim.gatePassed &&
      item.current_step >= gateStep
    ) {
      item.status = 'attention';
      item.attention_reason = 'CAPTCHA detected';
      item.message = 'Waiting for you to solve the challenge';
      continue;
    }
    item.current_step = Math.min(item.total_steps, item.current_step + 1);
    item.last_completed_step = item.current_step;
    if (item.current_step >= item.total_steps) {
      if (sim && item.profile_id === sim.failProfile) {
        item.status = 'failed';
        item.error = 'Selector not found: button[name="submit"]';
        item.message = 'Final step failed';
      } else {
        item.status = 'completed';
        item.message = 'Completed';
      }
    }
  }
  recomputeRun(run);
}
function progressFactory(job: ProfileFactoryJob): void {
  if (job.status !== 'running') return;
  const start = factoryStart.get(job.id) ?? Date.parse(job.created_at);
  const target = Math.min(job.quantity, Math.floor((Date.now() - start) / 1500));
  for (let i = 0; i < target; i += 1) {
    const item = job.items[i];
    if (item && item.status === 'pending') {
      item.profile_id = newId('prof');
      item.status = job.start_automation ? 'Setup complete' : 'Ready';
      job.created_count += 1;
    }
  }
  if (job.created_count >= job.quantity) job.status = 'completed';
}
function requireRun(id: string): AutomationRun {
  const run = mockRuns.find((x) => x.id === id);
  if (!run) throw new ApiError(404, 'run_not_found', 'Automation run not found.');
  return run;
}

// --- Shopify Builder mock state + draft-build simulation ---------------------
const PLAN_STEP_KEYS = [
  'product_csv',
  'analysis',
  'identity',
  'content',
  'policies',
  'navigation',
  'preset',
  'design',
  'theme',
] as const;
const CAP_FOR_STEP: Partial<Record<(typeof PLAN_STEP_KEYS)[number], StoreCapabilityKey>> = {
  product_csv: 'write_products',
  content: 'write_pages',
  policies: 'write_legal_policies',
  navigation: 'write_navigation',
  design: 'write_themes',
  theme: 'write_themes',
};
const mockThemes: ThemeLibrary = {
  integrated: [
    { id: 'thm_dawn', name: 'Dawn', role: 'demo', presets: ['Default', 'Bright', 'Studio'] },
    { id: 'thm_horizon', name: 'Horizon', role: 'demo', presets: ['Default', 'Bold'] },
  ],
  store: [{ id: 'thm_main', name: 'Live theme', role: 'main', presets: ['Default'] }],
};
const mockCatalogs: ProductCatalog[] = [
  { id: 'cat_vst', name: 'VST plugins', niche: 'audio-software', product_count: 24 },
  { id: 'cat_moto', name: 'Motorsport gear', niche: 'motorsport', product_count: 40 },
  { id: 'cat_home', name: 'Home & living', niche: 'home', product_count: 60 },
];
const mockStores: ShopifyStore[] = [];
const mockPlans: BuildPlan[] = [];
let mockAi: AiImageSettings = {
  enabled: false,
  provider: 'openai',
  model: 'gpt-image-2',
  has_api_key: false,
};
const planStart = new Map<string, number>();
const storeProfiles = new Map<string, StoreProfile>();

function capsFromScopes(scopes: string[]): Record<StoreCapabilityKey, boolean> {
  const has = (scope: string) => scopes.includes(scope);
  return {
    write_products: has('write_products'),
    write_pages: has('write_content'),
    write_legal_policies: has('write_legal_policies') || has('write_content'),
    write_navigation: has('write_navigation') || has('write_content'),
    write_themes: has('write_themes'),
  };
}
function requireStore(id: string): ShopifyStore {
  const store = mockStores.find((x) => x.id === id);
  if (!store) throw new ApiError(404, 'store_not_found', 'Store not found.');
  return store;
}
function requirePlan(planId: string): BuildPlan {
  const plan = mockPlans.find((x) => x.id === planId);
  if (!plan) throw new ApiError(404, 'plan_not_found', 'Build plan not found.');
  return plan;
}
function themeById(id: string): ThemeInfo | undefined {
  return [...mockThemes.integrated, ...mockThemes.store].find((t) => t.id === id);
}
function progressPlan(plan: BuildPlan): void {
  if (plan.status !== 'running') return;
  const start = planStart.get(plan.id) ?? Date.parse(plan.created_at);
  const done = Math.floor((Date.now() - start) / 800);
  const runnable = plan.steps.filter((s) => s.status !== 'blocked');
  runnable.forEach((step, index) => {
    if (index < done) step.status = 'completed';
    else if (index === done) step.status = 'running';
    else step.status = 'ready';
  });
  if (done >= runnable.length) {
    const blocked = plan.steps.some((s) => s.status === 'blocked');
    plan.status = blocked ? 'partial' : 'completed';
    const domain =
      mockStores.find((s) => s.id === plan.store_id)?.shop_domain ?? 'example.myshopify.com';
    plan.admin_url = `https://${domain}/admin/themes`;
    plan.preview_url = `https://${domain}?preview_theme_id=99001`;
  }
}

// --- Session history / backups / media mock state ----------------------------
const EXIT_REASONS: SessionExitReason[] = ['closed', 'stopped', 'crashed', 'timeout'];
const mockSessions: RuntimeSessionRecord[] = [];
const mockBackups: BackupArchive[] = [
  {
    id: 'bkp_seed',
    created_at: now(),
    size_bytes: 2_400_000,
    automatic: true,
    verified: true,
    contents: ['profiles', 'proxies', 'workspaces', 'extensions'],
  },
];
let mockMediaSettings: MediaSettings = { enabled: false };
const mockMediaAssets: MediaAsset[] = [
  {
    id: 'media_cam1',
    name: 'Office webcam',
    kind: 'camera',
    format: 'video/mp4',
    size_bytes: 5_800_000,
    assigned_profile_count: 2,
    created_at: now(),
  },
  {
    id: 'media_still',
    name: 'Portrait still',
    kind: 'camera',
    format: 'image/jpeg',
    size_bytes: 240_000,
    assigned_profile_count: 0,
    created_at: now(),
  },
];
const mediaAssignments = new Map<string, Set<string>>();
const mockProxyProviders: ProxyProvider[] = [
  { id: 'iproyal', name: 'IPRoyal', configured: false },
  { id: 'seveneleven', name: '711Proxy', configured: false },
];

function makeSession(): OwnerSession {
  return { email: mockStore.owner.email ?? ownerEmail, csrf_token: 'mock-csrf-token' };
}

function transition(id: string, state: RuntimeState, message: string): void {
  const profile = mockStore.profiles.find((p) => p.id === id);
  if (!profile) return;
  profile.runtime_state = state;
  if (state === 'running') profile.last_opened_at = now();
  mockStore.emit('profile.runtime.changed', { profile_id: id, runtime_state: state, message });
}

function buildProfile(payload: Partial<ProfileCreatePayload>, name: string): ProfileRead {
  const proxy = payload.proxy_id
    ? (mockStore.proxies.find((p) => p.id === payload.proxy_id) ?? null)
    : null;
  const seed = payload.fingerprint_seed ?? randomSeed();
  const id = newId('prof');
  return {
    id,
    profile_directory: `${mockStore.settings.profile_root}\\${id}`,
    name,
    folder_id: payload.folder_id ?? null,
    workflow_status_id: payload.workflow_status_id ?? null,
    tag_ids: payload.tag_ids ?? [],
    notes: payload.notes ?? '',
    pinned: payload.pinned ?? false,
    startup_urls: payload.startup_urls ?? [],
    fingerprint_seed: seed,
    fingerprint_preset: payload.fingerprint_preset ?? 'consistent',
    browser_version_mode: payload.browser_version_mode ?? 'installed',
    browser_version: payload.browser_version ?? null,
    user_agent_mode: payload.user_agent_mode ?? 'automatic',
    custom_user_agent: payload.custom_user_agent ?? null,
    location: payload.location ?? defaultLocation(proxy),
    window: payload.window ?? defaultWindow(),
    behavior: payload.behavior ?? defaultBehavior(),
    proxy_id: payload.proxy_id ?? null,
    test_proxy_before_launch:
      payload.test_proxy_before_launch ?? mockStore.settings.default_test_before_launch,
    fingerprint_revision: 1,
    fingerprint_config_hash: fakeConfigHash(seed),
    runtime_state: 'stopped',
    created_at: now(),
    updated_at: now(),
    last_opened_at: null,
    total_runtime_seconds: 0,
    deleted_at: null,
  };
}

function parseProxyString(raw: string): ParsedProxy {
  const trimmed = raw.trim();
  if (!trimmed) throw new ApiError(422, 'proxy_parse_failed', 'Enter a proxy to parse.');
  let scheme: ProxyScheme = 'http';
  let rest = trimmed;
  const schemeMatch = /^(https?|socks5h|socks5|direct):\/\//i.exec(trimmed);
  if (schemeMatch) {
    scheme = schemeMatch[1].toLowerCase() as ProxyScheme;
    rest = trimmed.slice(schemeMatch[0].length);
  }
  let username: string | null = null;
  let hasPassword = false;
  let hostPort = rest;
  if (rest.includes('@')) {
    const [creds, hp] = rest.split('@');
    hostPort = hp;
    const [user, pass] = creds.split(':');
    username = user || null;
    hasPassword = Boolean(pass);
  } else {
    const parts = rest.split(':');
    if (parts.length === 4) {
      hostPort = `${parts[0]}:${parts[1]}`;
      username = parts[2] || null;
      hasPassword = Boolean(parts[3]);
    }
  }
  const [host, portText] = hostPort.split(':');
  const port = portText ? Number(portText) : null;
  if (!host || (port !== null && Number.isNaN(port))) {
    throw new ApiError(422, 'proxy_parse_failed', 'Could not read host and port from that value.');
  }
  return { scheme, host, port, username, has_password: hasPassword };
}

function buildQuickResult(proxy: Proxy): ProxyQuickTest {
  if (proxy.scheme === 'direct') {
    return {
      ok: true,
      connectivity: true,
      exit_ip: '203.0.113.7',
      exit_ip_matches: true,
      latency_ms: 18,
      country: 'US',
      country_name: 'United States',
      city: 'Local network',
      timezone: 'America/New_York',
      latitude: 40.71427,
      longitude: -74.00597,
      zip_code: '10004',
      asn: 'AS64500',
      organization: 'Direct connection',
      checked_at: now(),
      error: null,
    };
  }
  const reachable = proxy.reputation !== 'malicious';
  // Simulate a GeoIP lookup on the exit IP: fall back to a realistic profile
  // when the proxy has no stored geo yet (a freshly added/parsed proxy).
  return {
    ok: reachable,
    connectivity: reachable,
    exit_ip: proxy.exit_ip ?? '172.96.5.74',
    exit_ip_matches: reachable,
    latency_ms: proxy.latency_ms ?? 180,
    country: proxy.country ?? 'US',
    country_name: proxy.country ? proxy.country : 'United States',
    city: proxy.city ?? 'New York City',
    timezone: proxy.timezone ?? 'America/New_York',
    latitude: 40.71427,
    longitude: -74.00597,
    zip_code: '10004',
    asn: proxy.asn ?? 'AS9009',
    organization: proxy.organization ?? 'M247 Europe SRL',
    checked_at: now(),
    error: reachable ? null : 'Connection refused by upstream proxy.',
  };
}

function buildQualityReport(proxy: Proxy): ProxyQualityReport {
  const bad = proxy.reputation === 'malicious' || proxy.reputation === 'suspicious';
  return {
    id: newId('rep'),
    proxy_id: proxy.id,
    state: 'completed',
    proxy_type: proxy.proxy_type,
    type_confidence: proxy.type_confidence ?? 0.8,
    reputation: proxy.reputation,
    matched_lists: proxy.reputation === 'malicious' ? ['abuse-db', 'generic-datacenter'] : [],
    google_outcome: bad ? 'captcha' : 'passed',
    turnstile_outcome: bad ? 'challenge' : 'passed',
    alignment: {
      http: { status: 'aligned', detail: 'Headers consistent with a Windows Chrome client.' },
      webrtc: {
        status: proxy.scheme === 'socks5' ? 'leak' : 'aligned',
        detail:
          proxy.scheme === 'socks5'
            ? 'Plain SOCKS5 delegates DNS locally; use SOCKS5H to resolve remotely.'
            : 'No non-proxied UDP candidates observed.',
      },
      dns: {
        status: proxy.scheme === 'socks5' ? 'mismatch' : 'aligned',
        detail:
          proxy.scheme === 'socks5'
            ? 'DNS resolved locally rather than at the proxy exit.'
            : 'DNS resolved through the proxy exit region.',
      },
      timezone: { status: bad ? 'mismatch' : 'aligned', detail: 'Compared to exit geolocation.' },
      locale: { status: 'aligned', detail: 'en-US consistent with exit country.' },
    },
    latency_ms: proxy.latency_ms ?? 180,
    exit_ip: proxy.exit_ip ?? '203.0.113.10',
    country: proxy.country,
    city: proxy.city,
    timezone: proxy.timezone,
    asn: proxy.asn,
    organization: proxy.organization,
    screenshot_path: `reports/proxy-quality/${proxy.id}/turnstile.png`,
    report_path: `reports/proxy-quality/${proxy.id}/report.json`,
    observed_scope: 'Snapshot from a single test run; upstream reputation can change over time.',
    checked_at: now(),
  };
}

function sortProfiles(list: ProfileRead[], sort: ProfileListParams['sort']): ProfileRead[] {
  const dir = sort?.startsWith('-') ? -1 : 1;
  const key = (sort ?? '-updated_at').replace(/^-/, '');
  const value = (p: ProfileRead): string => {
    switch (key) {
      case 'name':
        return p.name.toLowerCase();
      case 'created_at':
        return p.created_at;
      case 'last_opened_at':
        return p.last_opened_at ?? '';
      default:
        return p.updated_at;
    }
  };
  return [...list].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    const av = value(a);
    const bv = value(b);
    if (av < bv) return -1 * dir;
    if (av > bv) return 1 * dir;
    return 0;
  });
}

export const mockApi: ApiAdapter = {
  mode: 'mock',

  async authStatus(): Promise<AuthStatus> {
    await delay(60);
    return { setup_required: mockStore.owner.setupRequired };
  },
  async authSetup(payload: EmailPasswordRequest): Promise<OwnerSession> {
    await delay(160);
    mockStore.owner = { setupRequired: false, email: payload.email, loggedOut: false };
    const session = makeSession();
    setCsrfToken(session.csrf_token);
    return session;
  },
  async authLogin(payload: EmailPasswordRequest): Promise<OwnerSession> {
    await delay(160);
    if (mockStore.owner.setupRequired) {
      throw new ApiError(401, 'setup_required', 'Complete first-run setup first.');
    }
    mockStore.owner.email = payload.email || mockStore.owner.email;
    mockStore.owner.loggedOut = false;
    const session = makeSession();
    setCsrfToken(session.csrf_token);
    return session;
  },
  async authSession(): Promise<OwnerSession> {
    await delay(60);
    if (mockStore.owner.loggedOut) {
      throw new ApiError(401, 'unauthenticated', 'Sign in to continue.');
    }
    const session = makeSession();
    setCsrfToken(session.csrf_token);
    return session;
  },
  async authLogout() {
    await delay(80);
    mockStore.owner.loggedOut = true;
    setCsrfToken(null);
    return { ok: true };
  },
  async authLock() {
    await delay(80);
    mockStore.owner.loggedOut = true;
    setCsrfToken(null);
    return { ok: true };
  },
  async authChangePassword(_payload: ChangePasswordRequest) {
    await delay(140);
    setCsrfToken(null);
    return { ok: true };
  },

  async health() {
    return { ok: true };
  },

  async bootstrap(): Promise<AppBootstrap> {
    await delay(120);
    return {
      api_version: 'v1',
      platform: 'windows',
      owner_email: mockStore.owner.email ?? ownerEmail,
      capabilities: {
        authentication: true,
        profiles: true,
        catalogs: true,
        proxy_management: true,
        browser_runtime: true,
        fingerprint_diagnostics: true,
        settings: true,
        automation: true,
        shopify_builder: true,
        media: true,
        resources: true,
      },
      running_session_count: mockStore.profiles.filter(
        (profile) =>
          !profile.deleted_at &&
          ['starting', 'running', 'stopping'].includes(profile.runtime_state),
      ).length,
    };
  },

  async version(): Promise<AppVersion> {
    return {
      manager_api_version: 'v1',
      cloakbrowser_version: mockStore.settings.browser.version,
      chromium_version: mockStore.settings.browser.version,
    };
  },

  async listProfiles(params: ProfileListParams): Promise<Paginated<ProfileRead>> {
    await delay(140);
    let list = mockStore.profiles.filter((p) => !p.deleted_at);
    if (params.query) {
      const q = params.query.toLowerCase();
      list = list.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          p.notes.toLowerCase().includes(q) ||
          p.id.toLowerCase().includes(q) ||
          p.tag_ids.some((id) =>
            mockStore.tags
              .find((t) => t.id === id)
              ?.name.toLowerCase()
              .includes(q),
          ) ||
          (p.proxy_id
            ? (mockStore.proxies
                .find((x) => x.id === p.proxy_id)
                ?.label.toLowerCase()
                .includes(q) ?? false)
            : false),
      );
    }
    if (params.folder_id !== undefined && params.folder_id !== null) {
      list = list.filter((p) => p.folder_id === params.folder_id);
    }
    if (params.tag_id) list = list.filter((p) => p.tag_ids.includes(params.tag_id!));
    if (params.workflow_status_id)
      list = list.filter((p) => p.workflow_status_id === params.workflow_status_id);
    if (params.pinned !== undefined) list = list.filter((p) => p.pinned === params.pinned);

    list = sortProfiles(list, params.sort);
    const page = Math.max(1, params.page ?? 1);
    const pageSize = Math.max(1, params.page_size ?? mockStore.settings.rows_per_page);
    const total = list.length;
    const start = (page - 1) * pageSize;
    return {
      items: structuredClone(list.slice(start, start + pageSize)),
      total,
      page,
      page_size: pageSize,
      pages: Math.max(1, Math.ceil(total / pageSize)),
    };
  },

  async getProfile(id: string): Promise<ProfileRead> {
    await delay(80);
    return structuredClone(mockStore.requireProfile(id));
  },

  async createProfile(payload: ProfileCreatePayload): Promise<ProfileRead> {
    await delay(200);
    const profile = buildProfile(payload, payload.name);
    mockStore.profiles.unshift(profile);
    mockStore.recomputeProxyAssignments();
    mockStore.emit('profile.created', { profile: structuredClone(profile) });
    return structuredClone(profile);
  },

  async quickCreateProfile(payload: ProfileCreatePayload): Promise<ProfileRead> {
    await delay(160);
    const name = payload.name || `quick-profile-${mockStore.profiles.length + 1}`;
    const profile = buildProfile(payload, name);
    mockStore.profiles.unshift(profile);
    mockStore.emit('profile.created', { profile: structuredClone(profile) });
    return structuredClone(profile);
  },

  async updateProfile(id: string, payload: ProfileUpdatePayload): Promise<ProfileRead> {
    await delay(160);
    const profile = mockStore.requireProfile(id);
    if (payload.expected_updated_at !== profile.updated_at) {
      throw new ApiError(409, 'profile_conflict', 'The profile changed. Refresh before saving.');
    }
    const { expected_updated_at: _expected, ...changes } = payload;
    Object.assign(profile, changes, { updated_at: now() });
    mockStore.recomputeProxyAssignments();
    mockStore.emit('profile.updated', { profile: structuredClone(profile) });
    return structuredClone(profile);
  },

  async duplicateProfile(id: string): Promise<ProfileRead> {
    await delay(180);
    const source = mockStore.requireProfile(id);
    const copy = structuredClone(source);
    copy.id = newId('prof');
    copy.name = `${source.name}-copy`;
    copy.pinned = false;
    copy.fingerprint_seed = randomSeed();
    copy.fingerprint_revision = 1;
    copy.fingerprint_config_hash = fakeConfigHash(copy.fingerprint_seed);
    copy.runtime_state = 'stopped';
    copy.last_opened_at = null;
    copy.created_at = now();
    copy.updated_at = now();
    mockStore.profiles.unshift(copy);
    mockStore.recomputeProxyAssignments();
    mockStore.emit('profile.created', { profile: structuredClone(copy) });
    return structuredClone(copy);
  },

  async regenerateFingerprint(id: string): Promise<ProfileRead> {
    await delay(160);
    const profile = mockStore.requireProfile(id);
    profile.fingerprint_seed = randomSeed();
    profile.fingerprint_revision += 1;
    profile.fingerprint_config_hash = fakeConfigHash(profile.fingerprint_seed);
    profile.updated_at = now();
    mockStore.emit('profile.updated', { profile: structuredClone(profile) });
    return structuredClone(profile);
  },

  async startProfile(id: string): Promise<void> {
    await delay(120);
    const profile = mockStore.requireProfile(id);
    if (['starting', 'running', 'stopping'].includes(profile.runtime_state)) {
      throw new ApiError(409, 'profile_already_running', 'This profile is already running.');
    }
    transition(id, 'starting', profile.test_proxy_before_launch ? 'Testing proxy…' : 'Launching…');
    window.setTimeout(() => transition(id, 'running', 'Browser ready'), 900);
  },

  async stopProfile(id: string): Promise<void> {
    await delay(120);
    const profile = mockStore.requireProfile(id);
    if (!['running', 'starting', 'crashed'].includes(profile.runtime_state)) {
      throw new ApiError(409, 'profile_not_running', 'This profile is not running.');
    }
    transition(id, 'stopping', 'Closing browser…');
    window.setTimeout(() => transition(id, 'stopped', 'Ready'), 600);
  },

  async focusWindow(id: string) {
    await delay(60);
    mockStore.requireProfile(id);
    return { ok: true };
  },

  async moveProfileToTrash(id: string) {
    await delay(140);
    const profile = mockStore.requireProfile(id);
    profile.deleted_at = now();
    profile.runtime_state = 'stopped';
    mockStore.recomputeProxyAssignments();
    mockStore.emit('profile.deleted', { profile_id: id });
    return { ok: true };
  },

  async restoreProfile(id: string): Promise<ProfileRead> {
    await delay(140);
    const profile = mockStore.requireProfile(id);
    profile.deleted_at = null;
    mockStore.emit('profile.created', { profile: structuredClone(profile) });
    return structuredClone(profile);
  },

  async getProfileLogs(id: string, params = {}): Promise<ProfileLogs> {
    await delay(120);
    const profile = mockStore.requireProfile(id);
    const entries: ProfileLogs['items'] = [
      {
        id: 'log-1',
        profile_id: id,
        created_at: '2026-07-21T09:00:00Z',
        level: 'info',
        event: 'runtime.start_requested',
        message: 'Manager acquired profile lock.',
      },
      {
        id: 'log-2',
        profile_id: id,
        created_at: '2026-07-21T09:00:01Z',
        level: 'info',
        event: 'runtime.process_started',
        message: `Preset ${profile.fingerprint_preset}, seed ${profile.fingerprint_seed}.`,
      },
      {
        id: 'log-3',
        profile_id: id,
        created_at: '2026-07-21T09:00:02Z',
        level: 'info',
        event: 'runtime.preflight_failed',
        message: 'Proxy pre-launch test passed (median 148 ms).',
      },
      {
        id: 'log-4',
        profile_id: id,
        created_at: '2026-07-21T09:00:03Z',
        level: 'info',
        event: 'runtime.ready',
        message: 'Launched persistent context; browser ready.',
      },
      ...(profile.runtime_state === 'crashed'
        ? [
            {
              id: 'log-5',
              profile_id: id,
              created_at: '2026-07-21T09:05:00Z',
              level: 'error' as const,
              event: 'runtime.crashed',
              message: 'Browser process exited unexpectedly (code 1).',
            },
          ]
        : []),
    ];
    const page = params.page ?? 1;
    const pageSize = params.page_size ?? 50;
    const start = (page - 1) * pageSize;
    return {
      items: entries.slice(start, start + pageSize),
      total: entries.length,
      page,
      page_size: pageSize,
      pages: Math.max(1, Math.ceil(entries.length / pageSize)),
    };
  },

  async getProfileLogTail(id: string, params = {}): Promise<ProfileLogTail> {
    const history = await mockApi.getProfileLogs(id, { page: 1, page_size: 200 });
    const limit = params.limit ?? 50;
    const match = params.cursor?.match(/^mock-tail-(\d+)$/);
    const malformed = Boolean(params.cursor) && !match;
    const start = malformed ? Math.max(0, history.items.length - limit) : Number(match?.[1] ?? 0);
    const items = history.items.slice(start, start + limit);
    return {
      items,
      next_cursor: `mock-tail-${start + items.length}`,
      reset: malformed,
    };
  },

  async exportProfile(id: string) {
    await delay(120);
    const p = mockStore.requireProfile(id);
    const proxy = p.proxy_id ? mockStore.proxies.find((x) => x.id === p.proxy_id) : null;
    const document = {
      format: 'cloakbrowser-manager-profile',
      version: 1,
      exported_at: now(),
      profile: {
        name: p.name,
        fingerprint_preset: p.fingerprint_preset,
        browser_version_mode: p.browser_version_mode,
        browser_version: p.browser_version,
        user_agent_mode: p.user_agent_mode,
        startup_urls: p.startup_urls,
        location: p.location,
        window: p.window,
        behavior: p.behavior,
        proxy: proxy ? { scheme: proxy.scheme, host: proxy.host, port: proxy.port } : null,
      },
      extensions: [],
    };
    return {
      blob: new Blob([JSON.stringify(document)], { type: 'application/json' }),
      filename: `cloakbrowser-profile-${p.name}.json`,
    };
  },

  async importProfile(payload: Record<string, unknown>) {
    await delay(200);
    if (
      payload.format !== 'cloakbrowser-manager-profile' ||
      payload.version !== 1 ||
      typeof payload.exported_at !== 'string' ||
      !payload.profile ||
      typeof payload.profile !== 'object' ||
      Array.isArray(payload.profile)
    ) {
      throw new ApiError(
        422,
        'profile_import_invalid',
        'Expected a CloakBrowser Manager profile export with format and version 1.',
      );
    }
    const source = payload.profile as Record<string, unknown>;
    const name =
      typeof source.name === 'string' && source.name
        ? `${source.name}-imported`
        : 'imported-profile';
    const profile = buildProfile({}, name);
    mockStore.profiles.unshift(profile);
    mockStore.emit('profile.created', { profile: structuredClone(profile) });
    return { profile_id: profile.id, profile_name: profile.name, warnings: [] };
  },

  async importCookies(id: string, payload: CookieImportPayload): Promise<CookieImportResult> {
    await delay(220);
    mockStore.requireProfile(id);
    const lines = payload.content.split('\n').filter((l) => l.trim() && !l.startsWith('#'));
    const imported = Math.max(1, lines.length);
    return {
      imported_count: imported,
      skipped_count: 0,
      rejected_count: 0,
      format: payload.format,
      warnings: imported > 200 ? [{ index: 0, code: 'large_cookie_set' }] : [],
    };
  },

  async exportCookies(id: string, format: 'playwright' | 'netscape') {
    const profile = mockStore.requireProfile(id);
    return {
      blob: new Blob([format === 'netscape' ? '# Netscape HTTP Cookie File\n' : '[]\n']),
      filename: `cloakbrowser-cookies-${profile.name}.${format === 'netscape' ? 'txt' : 'json'}`,
    };
  },

  async openProfileDirectory(id: string) {
    return { profile_directory: mockStore.requireProfile(id).profile_directory };
  },

  async bulkProfiles(request: BulkProfileRequest): Promise<BulkProfileResult> {
    await delay(200);
    const updated: string[] = [];
    for (const id of request.ids) {
      const profile = mockStore.profiles.find((p) => p.id === id);
      if (!profile) continue;
      switch (request.action) {
        case 'pin':
          profile.pinned = true;
          break;
        case 'unpin':
          profile.pinned = false;
          break;
        case 'move_folder':
          profile.folder_id = request.folder_id ?? null;
          break;
        case 'set_status':
          profile.workflow_status_id = request.workflow_status_id ?? null;
          break;
        case 'trash':
          profile.deleted_at = now();
          break;
        case 'restore':
          profile.deleted_at = null;
          break;
      }
      profile.updated_at = now();
      updated.push(id);
      if (request.action === 'trash') mockStore.emit('profile.deleted', { profile_id: id });
      else mockStore.emit('profile.updated', { profile: structuredClone(profile) });
    }
    mockStore.recomputeProxyAssignments();
    return { updated_ids: updated, count: updated.length };
  },

  // Folders / tags / statuses
  async listFolders(): Promise<Folder[]> {
    await delay(80);
    return mockStore.foldersWithCounts();
  },
  async createFolder(name: string): Promise<Folder> {
    await delay(120);
    const folder: Folder = {
      id: newId('fld'),
      name,
      position: mockStore.folders.length,
      created_at: now(),
      updated_at: now(),
      profile_count: 0,
      running_count: 0,
    };
    mockStore.folders.push(folder);
    return structuredClone(folder);
  },
  async renameFolder(id: string, name: string): Promise<Folder> {
    await delay(100);
    const folder = mockStore.folders.find((f) => f.id === id);
    if (!folder) throw new ApiError(404, 'folder_not_found', 'That folder no longer exists.');
    folder.name = name;
    folder.updated_at = now();
    return structuredClone(folder);
  },
  async reorderFolders(orderedIds: string[]): Promise<Folder[]> {
    await delay(100);
    mockStore.folders.sort((a, b) => orderedIds.indexOf(a.id) - orderedIds.indexOf(b.id));
    mockStore.folders.forEach((f, i) => (f.position = i));
    return mockStore.foldersWithCounts();
  },
  async deleteFolder(id: string) {
    await delay(120);
    mockStore.folders = mockStore.folders.filter((f) => f.id !== id);
    for (const profile of mockStore.profiles) {
      if (profile.folder_id === id) profile.folder_id = null;
    }
    return { ok: true };
  },
  async listTags() {
    await delay(60);
    return structuredClone(mockStore.tags);
  },
  async createTag(payload: { name: string; color?: string }) {
    await delay(100);
    const name = payload.name.trim();
    const existing = mockStore.tags.find((t) => t.name.toLowerCase() === name.toLowerCase());
    if (existing) return structuredClone(existing);
    const tag = { id: newId('tag'), name, color: payload.color ?? '#64748B' };
    mockStore.tags.push(tag);
    return structuredClone(tag);
  },
  async listWorkflowStatuses() {
    await delay(60);
    return structuredClone(mockStore.statuses);
  },

  async listExtensions(): Promise<Extension[]> {
    await delay(60);
    return structuredClone(mockStore.extensions);
  },
  async registerExtension(directory: string): Promise<Extension> {
    await delay(80);
    const name = directory.split(/[\\/]/).filter(Boolean).at(-1) ?? 'extension';
    const extension: Extension = {
      id: newId('ext'),
      directory,
      name,
      version: '1.0.0',
      description: 'Local unpacked extension.',
      manifest_version: 3,
      permissions: [],
      enabled: true,
      manifest_hash: fakeConfigHash(directory),
      created_at: now(),
      updated_at: now(),
    };
    mockStore.extensions.push(extension);
    return structuredClone(extension);
  },
  async updateExtension(id: string, patch: { enabled?: boolean; refresh?: boolean }) {
    await delay(60);
    const extension = mockStore.extensions.find((item) => item.id === id);
    if (!extension) throw new ApiError(404, 'extension_not_found', 'Extension not found.');
    if (patch.enabled !== undefined) extension.enabled = patch.enabled;
    extension.updated_at = now();
    return structuredClone(extension);
  },
  async unregisterExtension(id: string) {
    await delay(60);
    mockStore.extensions = mockStore.extensions.filter((item) => item.id !== id);
  },
  async getProfileExtensions(id: string) {
    await delay(40);
    mockStore.requireProfile(id);
    return { extension_ids: structuredClone(mockStore.profileExtensionIds[id] ?? []) };
  },
  async setProfileExtensions(id: string, extensionIds: string[]) {
    mockStore.requireProfile(id);
    const uuidPattern =
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    const validIds = new Set(mockStore.extensions.map((extension) => extension.id));
    if (
      new Set(extensionIds).size !== extensionIds.length ||
      extensionIds.some(
        (extensionId) => !uuidPattern.test(extensionId) || !validIds.has(extensionId),
      )
    ) {
      throw new ApiError(
        422,
        'invalid_extension_reference',
        'Extension assignments must contain unique registered extension UUIDs.',
      );
    }
    mockStore.profileExtensionIds[id] = structuredClone(extensionIds);
    return { extension_ids: structuredClone(extensionIds) };
  },

  // Proxies
  async listProxies(): Promise<Proxy[]> {
    await delay(120);
    mockStore.recomputeProxyAssignments();
    return structuredClone(mockStore.proxies);
  },
  async getProxy(id: string): Promise<Proxy> {
    await delay(80);
    return structuredClone(mockStore.requireProxy(id));
  },
  async createProxy(payload: ProxyWritePayload): Promise<Proxy> {
    await delay(160);
    const hasPassword = Boolean(payload.password);
    const proxy: Proxy = {
      id: newId('px'),
      label: payload.label,
      scheme: payload.scheme,
      host: payload.host,
      port: payload.port,
      username: payload.username,
      has_password: hasPassword,
      masked_endpoint: maskEndpoint(
        payload.scheme,
        payload.host,
        payload.port,
        Boolean(payload.username) || hasPassword,
      ),
      test_before_launch: payload.test_before_launch,
      assigned_profile_count: 0,
      exit_ip: null,
      country: null,
      city: null,
      timezone: null,
      asn: null,
      organization: null,
      proxy_type: null,
      type_confidence: null,
      reputation: null,
      latency_ms: null,
      last_checked_at: null,
      created_at: now(),
      updated_at: now(),
    };
    mockStore.proxies.push(proxy);
    mockStore.emit('proxy.updated', { proxy: structuredClone(proxy) });
    return structuredClone(proxy);
  },
  async updateProxy(id: string, payload: ProxyWritePayload): Promise<Proxy> {
    await delay(140);
    const proxy = mockStore.requireProxy(id);
    proxy.label = payload.label;
    proxy.scheme = payload.scheme;
    proxy.host = payload.host;
    proxy.port = payload.port;
    proxy.username = payload.username;
    if (payload.password) proxy.has_password = true;
    proxy.test_before_launch = payload.test_before_launch;
    proxy.masked_endpoint = maskEndpoint(
      payload.scheme,
      payload.host,
      payload.port,
      Boolean(payload.username) || proxy.has_password,
    );
    proxy.updated_at = now();
    mockStore.emit('proxy.updated', { proxy: structuredClone(proxy) });
    return structuredClone(proxy);
  },
  async deleteProxy(id: string) {
    await delay(120);
    const proxy = mockStore.requireProxy(id);
    if (proxy.assigned_profile_count > 0) {
      throw new ApiError(
        409,
        'proxy_in_use',
        'This proxy is assigned to profiles. Reassign them before deleting it.',
      );
    }
    mockStore.proxies = mockStore.proxies.filter((p) => p.id !== id);
    return { ok: true };
  },
  async parseProxy(raw: string): Promise<ParsedProxy> {
    await delay(80);
    return parseProxyString(raw);
  },
  async quickTestProxy(id: string): Promise<ProxyQuickTest> {
    const proxy = mockStore.requireProxy(id);
    const phases = ['Connecting', 'Resolving exit IP', 'Measuring latency'];
    for (let i = 0; i < phases.length; i += 1) {
      await delay(160);
      mockStore.emit('proxy.test.progress', {
        proxy_id: id,
        kind: 'quick',
        phase: phases[i],
        progress: (i + 1) / phases.length,
        message: phases[i],
      });
    }
    const result = buildQuickResult(proxy);
    proxy.latency_ms = result.latency_ms;
    proxy.exit_ip = result.exit_ip;
    proxy.country = result.country;
    proxy.city = result.city;
    proxy.timezone = result.timezone;
    proxy.asn = result.asn;
    proxy.organization = result.organization;
    proxy.last_checked_at = result.checked_at;
    mockStore.emit('proxy.updated', { proxy: structuredClone(proxy) });
    mockStore.emit('proxy.test.completed', {
      proxy_id: id,
      kind: 'quick',
      ok: result.ok,
      report_id: null,
    });
    return result;
  },
  async qualityTestProxy(id: string): Promise<ProxyQualityReport> {
    const proxy = mockStore.requireProxy(id);
    const phases = [
      'Connecting through proxy',
      'Classifying IP type',
      'Checking reputation lists',
      'Google reachability control',
      'Third-party Turnstile demo',
      'DNS / WebRTC / timezone alignment',
    ];
    for (let i = 0; i < phases.length; i += 1) {
      await delay(200);
      mockStore.emit('proxy.test.progress', {
        proxy_id: id,
        kind: 'quality',
        phase: phases[i],
        progress: (i + 1) / phases.length,
        message: phases[i],
      });
    }
    const report = buildQualityReport(proxy);
    mockStore.reports.unshift(report);
    proxy.last_checked_at = report.checked_at;
    proxy.latency_ms = report.latency_ms;
    proxy.reputation = report.reputation;
    mockStore.emit('proxy.updated', { proxy: structuredClone(proxy) });
    mockStore.emit('proxy.test.completed', {
      proxy_id: id,
      kind: 'quality',
      ok: report.state === 'completed',
      report_id: report.id,
    });
    return structuredClone(report);
  },
  async getProxyReports(id: string): Promise<ProxyQualityReport[]> {
    await delay(100);
    return structuredClone(mockStore.reports.filter((r) => r.proxy_id === id));
  },

  // Diagnostics / settings
  async listDiagnostics(params = {}): Promise<Paginated<DiagnosticRun>> {
    await delay(120);
    let runs = [...mockStore.diagnostics];
    if (params.profile) runs = runs.filter((run) => run.profile_id === params.profile);
    if (params.kind) runs = runs.filter((run) => run.kind === params.kind);
    if (params.status) runs = runs.filter((run) => run.status === params.status);
    const page = params.page ?? 1;
    const pageSize = params.page_size ?? 20;
    const start = (page - 1) * pageSize;
    return {
      items: structuredClone(runs.slice(start, start + pageSize)),
      total: runs.length,
      page,
      page_size: pageSize,
      pages: Math.max(1, Math.ceil(runs.length / pageSize)),
    };
  },
  async getDiagnostic(id: string): Promise<DiagnosticRun> {
    await delay(80);
    const diag = mockStore.diagnostics.find((d) => d.id === id);
    if (!diag)
      throw new ApiError(404, 'diagnostic_not_found', 'That diagnostic run no longer exists.');
    return structuredClone(diag);
  },
  async runDirectGoogleControl(): Promise<DiagnosticRun> {
    await delay(400);
    const diag: DiagnosticRun = {
      id: newId('diag'),
      kind: 'direct_google_control',
      profile_id: null,
      status: 'passed',
      target_url: 'https://www.google.com/search?q=CloakBrowser+diagnostic',
      requested_at: now(),
      started_at: now(),
      completed_at: now(),
      progress: 100,
      summary: 'Direct-network Google control reachable; no challenge.',
      findings: { page_loaded: true, captcha_detected: false, results_visible: true },
      screenshot_url: null,
      report_url: null,
      error_code: null,
      error_message: null,
    };
    mockStore.diagnostics.unshift(diag);
    mockStore.emit('diagnostic.completed', {
      diagnostic_id: diag.id,
      profile_id: null,
      kind: diag.kind,
      status: diag.status,
      progress: 100,
      error_code: null,
    });
    return structuredClone(diag);
  },
  async runPixelscan(profileId: string): Promise<DiagnosticRun> {
    return this.runDiagnostic('pixelscan', profileId);
  },
  async runDiagnostic(kind: Exclude<DiagnosticKind, 'direct_google_control'>, profileId: string) {
    await delay(300);
    mockStore.requireProfile(profileId);
    const targets: Record<Exclude<DiagnosticKind, 'direct_google_control'>, string> = {
      pixelscan: 'https://pixelscan.net/',
      iphey: 'https://iphey.com/',
      cloudflare: 'https://challenge.cloudflare.com/turnstile/v0/generic/',
      google_search: 'https://www.google.com/search?q=CloakBrowser+browser+diagnostic',
    };
    const diagnosticId = newId('diag');
    const diag: DiagnosticRun = {
      id: diagnosticId,
      kind,
      profile_id: profileId,
      status: 'passed',
      target_url: targets[kind],
      requested_at: now(),
      started_at: now(),
      completed_at: now(),
      progress: 100,
      summary: 'Diagnostic completed.',
      findings: {},
      screenshot_url: null,
      report_url: `/api/v1/diagnostics/${diagnosticId}/artifacts/report`,
      error_code: null,
      error_message: null,
    };
    mockStore.diagnostics.unshift(diag);
    mockStore.emit('diagnostic.completed', {
      diagnostic_id: diag.id,
      profile_id: profileId,
      kind,
      status: diag.status,
      progress: 100,
      error_code: null,
    });
    return structuredClone(diag);
  },
  async cancelDiagnostic(id: string) {
    const run = mockStore.diagnostics.find((item) => item.id === id);
    if (!run) throw new ApiError(404, 'diagnostic_not_found', 'Diagnostic not found.');
    run.status = 'cancelled';
    run.progress = Math.min(run.progress, 99);
    run.completed_at = now();
    run.summary = 'Diagnostic cancelled.';
    return structuredClone(run);
  },
  async getSettings(): Promise<Settings> {
    await delay(80);
    return structuredClone(mockStore.settings);
  },
  async updateSettings(patch: Partial<Settings>): Promise<Settings> {
    await delay(140);
    mockStore.settings = { ...mockStore.settings, ...patch };
    return structuredClone(mockStore.settings);
  },
  async checkBrowserUpdate(): Promise<Settings> {
    await delay(80);
    return structuredClone(mockStore.settings);
  },

  async getResources(): Promise<ResourceSnapshot> {
    await delay(60);
    const running = mockStore.profiles.filter(
      (p) => !p.deleted_at && ['running', 'starting', 'stopping'].includes(p.runtime_state),
    );
    const profiles = running
      .map((p) => ({
        profile_id: p.id,
        profile_name: p.name,
        runtime_state: p.runtime_state,
        cpu_percent: Math.round(Math.random() * 180) / 10,
        memory_bytes: Math.round(180e6 + Math.random() * 420e6),
        process_count: 4 + Math.floor(Math.random() * 6),
      }))
      .sort((a, b) => b.cpu_percent - a.cpu_percent || b.memory_bytes - a.memory_bytes);
    const browsersMem = profiles.reduce((sum, r) => sum + r.memory_bytes, 0);
    const browsersCpu = Math.round(profiles.reduce((sum, r) => sum + r.cpu_percent, 0) * 10) / 10;
    const browsersProc = profiles.reduce((sum, r) => sum + r.process_count, 0);
    const totalMem = 16 * 1024 ** 3;
    const usedMem = 6 * 1024 ** 3 + browsersMem;
    return {
      generated_at: new Date().toISOString(),
      system: {
        cpu_percent: Math.round((10 + Math.random() * 30) * 10) / 10,
        memory_percent: Math.round((usedMem / totalMem) * 1000) / 10,
        memory_used_bytes: usedMem,
        memory_total_bytes: totalMem,
        logical_cpus: 12,
      },
      backend: {
        cpu_percent: Math.round(Math.random() * 30) / 10,
        memory_bytes: Math.round(120e6 + Math.random() * 40e6),
        process_count: 1,
      },
      browsers: {
        cpu_percent: browsersCpu,
        memory_bytes: browsersMem,
        process_count: browsersProc,
        profiles_running: profiles.length,
      },
      profiles,
    };
  },

  async listTemplates(): Promise<AutomationTemplate[]> {
    await delay(60);
    return structuredClone(mockTemplates);
  },
  async getTemplate(id: string): Promise<AutomationTemplate> {
    await delay(40);
    const tpl = mockTemplates.find((x) => x.id === id);
    if (!tpl) throw new ApiError(404, 'template_not_found', 'Template not found.');
    return structuredClone(tpl);
  },
  async saveTemplate(id, payload): Promise<AutomationTemplate> {
    await delay(80);
    const variables = deriveVars(payload.steps);
    const existing = mockTemplates.find((x) => x.id === id);
    if (existing) {
      Object.assign(existing, { ...payload, variables, updated_at: now() });
      return structuredClone(existing);
    }
    const created: AutomationTemplate = {
      id,
      ...payload,
      variables,
      created_at: now(),
      updated_at: now(),
    };
    mockTemplates.push(created);
    return structuredClone(created);
  },
  async deleteTemplate(id: string): Promise<void> {
    await delay(60);
    const index = mockTemplates.findIndex((x) => x.id === id);
    if (index >= 0) mockTemplates.splice(index, 1);
  },

  async startRecording(payload): Promise<AutomationRecording> {
    await delay(120);
    const rec: AutomationRecording = {
      id: newId('rec'),
      name: payload.name,
      description: payload.description,
      profile_id: payload.profile_id,
      status: 'recording',
      step_count: 0,
      template_id: null,
      created_at: now(),
    };
    mockRecordings.push(rec);
    return structuredClone(rec);
  },
  async getRecording(id: string): Promise<AutomationRecording> {
    await delay(40);
    const rec = mockRecordings.find((x) => x.id === id);
    if (!rec) throw new ApiError(404, 'recording_not_found', 'Recording not found.');
    progressRecording(rec);
    return structuredClone(rec);
  },
  async stopRecording(id: string): Promise<AutomationTemplate> {
    await delay(120);
    const rec = mockRecordings.find((x) => x.id === id);
    if (!rec) throw new ApiError(404, 'recording_not_found', 'Recording not found.');
    progressRecording(rec);
    rec.status = 'stopped';
    const steps = sampleSteps().slice(0, Math.max(3, Math.min(6, rec.step_count || 6)));
    const tpl: AutomationTemplate = {
      id: newId('tpl'),
      name: rec.name,
      description: rec.description,
      steps,
      variables: deriveVars(steps),
      created_at: now(),
      updated_at: now(),
    };
    mockTemplates.push(tpl);
    rec.template_id = tpl.id;
    return structuredClone(tpl);
  },
  async cancelRecording(id: string): Promise<void> {
    await delay(60);
    const rec = mockRecordings.find((x) => x.id === id);
    if (rec) rec.status = 'cancelled';
  },

  async startRun(templateId, payload): Promise<AutomationRun> {
    await delay(140);
    const tpl = mockTemplates.find((x) => x.id === templateId);
    if (!tpl) throw new ApiError(404, 'template_not_found', 'Template not found.');
    if (payload.assignments.length === 0)
      throw new ApiError(422, 'no_assignments', 'Select at least one profile.');
    const total = Math.max(3, tpl.steps.length);
    const items: AutomationRunItem[] = payload.assignments.map((assignment) => {
      const profile = mockStore.profiles.find((x) => x.id === assignment.profile_id);
      return {
        profile_id: assignment.profile_id,
        profile_name: profile?.name ?? assignment.profile_id,
        status: 'pending',
        current_step: 0,
        total_steps: total,
        last_completed_step: 0,
        message: null,
        attention_reason: null,
        error: null,
      };
    });
    const run: AutomationRun = {
      id: newId('run'),
      template_id: tpl.id,
      template_name: tpl.name,
      status: 'running',
      max_parallel: payload.max_parallel,
      total: items.length,
      completed_count: 0,
      failed_count: 0,
      attention_count: 0,
      created_at: now(),
      started_at: now(),
      finished_at: null,
      items,
    };
    mockRuns.unshift(run);
    runSim.set(run.id, {
      gateProfile: items[0]?.profile_id ?? null,
      gatePassed: false,
      failProfile: items.length > 1 ? items[items.length - 1].profile_id : null,
    });
    return structuredClone(run);
  },
  async getRun(id: string): Promise<AutomationRun> {
    await delay(40);
    const run = requireRun(id);
    progressRun(run);
    return structuredClone(run);
  },
  async cancelRun(id: string): Promise<AutomationRun> {
    await delay(80);
    const run = requireRun(id);
    run.items.forEach((item) => {
      if (!TERMINAL.includes(item.status)) item.status = 'cancelled';
    });
    run.status = 'cancelled';
    run.finished_at = now();
    recomputeRun(run);
    return structuredClone(run);
  },
  async continueRunProfile(runId, profileId): Promise<AutomationRun> {
    await delay(80);
    const run = requireRun(runId);
    const sim = runSim.get(runId);
    if (sim && sim.gateProfile === profileId) sim.gatePassed = true;
    const item = run.items.find((i) => i.profile_id === profileId);
    if (item && item.status === 'attention') {
      item.status = 'running';
      item.attention_reason = null;
      item.message = 'Resumed';
    }
    recomputeRun(run);
    return structuredClone(run);
  },
  async retryRunProfile(runId, profileId): Promise<AutomationRun> {
    await delay(80);
    const run = requireRun(runId);
    const sim = runSim.get(runId);
    if (sim && sim.failProfile === profileId) sim.failProfile = null;
    const item = run.items.find((i) => i.profile_id === profileId);
    if (item) {
      item.status = 'running';
      item.current_step = item.last_completed_step;
      item.error = null;
      item.message = 'Retrying';
    }
    if (run.status !== 'running') {
      run.status = 'running';
      run.finished_at = null;
    }
    recomputeRun(run);
    return structuredClone(run);
  },
  async markRunProfileCompleted(runId, profileId): Promise<AutomationRun> {
    await delay(60);
    const run = requireRun(runId);
    const item = run.items.find((i) => i.profile_id === profileId);
    if (item) {
      item.status = 'completed';
      item.current_step = item.total_steps;
      item.attention_reason = null;
      item.error = null;
      item.message = 'Marked completed';
    }
    recomputeRun(run);
    return structuredClone(run);
  },

  async getCredentialPool(): Promise<CredentialPoolSummary> {
    await delay(40);
    return { ...mockPool };
  },
  async importCredentials(text: string): Promise<CredentialPoolSummary> {
    await delay(100);
    const added = text
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line.includes(':')).length;
    mockPool = {
      ...mockPool,
      available: mockPool.available + added,
      total: mockPool.total + added,
    };
    return { ...mockPool };
  },

  async listFactoryJobs(): Promise<ProfileFactoryJob[]> {
    await delay(60);
    mockFactoryJobs.forEach(progressFactory);
    return structuredClone(mockFactoryJobs);
  },
  async startFactoryJob(payload): Promise<ProfileFactoryJob> {
    await delay(140);
    const items: ProfileFactoryItem[] = Array.from({ length: payload.quantity }, () => ({
      id: newId('fi'),
      profile_id: null,
      status: 'pending',
      message: null,
    }));
    const job: ProfileFactoryJob = {
      id: newId('fac'),
      status: 'running',
      quantity: payload.quantity,
      name_prefix: payload.name_prefix,
      automation_template_id: payload.automation_template_id ?? null,
      start_automation: payload.start_automation,
      created_count: 0,
      failed_count: 0,
      items,
      created_at: now(),
    };
    mockFactoryJobs.unshift(job);
    factoryStart.set(job.id, Date.now());
    return structuredClone(job);
  },
  async getFactoryJob(id: string): Promise<ProfileFactoryJob> {
    await delay(40);
    const job = mockFactoryJobs.find((x) => x.id === id);
    if (!job) throw new ApiError(404, 'factory_not_found', 'Factory job not found.');
    progressFactory(job);
    return structuredClone(job);
  },
  async cancelFactoryJob(id: string): Promise<ProfileFactoryJob> {
    await delay(80);
    const job = mockFactoryJobs.find((x) => x.id === id);
    if (!job) throw new ApiError(404, 'factory_not_found', 'Factory job not found.');
    job.items.forEach((item) => {
      if (item.status === 'pending') item.status = 'cancelled';
    });
    job.status = 'cancelled';
    return structuredClone(job);
  },

  async listStores(): Promise<ShopifyStore[]> {
    await delay(60);
    return structuredClone(mockStores);
  },
  async connectStore(payload): Promise<ShopifyStore> {
    await delay(220);
    if (!payload.shop_domain.trim() || !payload.client_id.trim())
      throw new ApiError(422, 'invalid_store', 'A shop domain and client ID are required.');
    const domain = payload.shop_domain.trim().replace(/^https?:\/\//, '');
    const scopes = [
      'read_products',
      'write_products',
      'write_content',
      'write_themes',
      'write_navigation',
    ];
    const store: ShopifyStore = {
      id: newId('store'),
      label: payload.label.trim() || domain,
      shop_domain: domain,
      connected: true,
      scopes,
      capabilities: capsFromScopes(scopes),
      shop_name: payload.label.trim() || domain.split('.')[0],
      product_count: 12 + Math.floor(Math.random() * 40),
      proxy_id: payload.proxy_id ?? null,
      exit_ip: payload.proxy_id ? `203.0.113.${10 + Math.floor(Math.random() * 200)}` : null,
      niche: null,
      language: null,
      created_at: now(),
      updated_at: now(),
    };
    mockStores.unshift(store);
    storeProfiles.set(store.id, {
      niche: null,
      language: null,
      store_name: store.shop_name ?? domain,
      support_email: `support@${domain}`,
    });
    return structuredClone(store);
  },
  async inspectStore(id: string): Promise<ShopifyStore> {
    await delay(200);
    const store = requireStore(id);
    store.niche = mockCatalogs[Math.floor(Math.random() * mockCatalogs.length)].niche;
    store.language = 'en';
    store.product_count = store.product_count ?? 12;
    store.updated_at = now();
    const profile = storeProfiles.get(id);
    if (profile) {
      profile.niche = store.niche;
      profile.language = store.language;
    }
    return structuredClone(store);
  },
  async setStoreNetworkRoute(id, proxyId): Promise<ShopifyStore> {
    await delay(120);
    const store = requireStore(id);
    store.proxy_id = proxyId;
    store.exit_ip = proxyId ? `203.0.113.${10 + Math.floor(Math.random() * 200)}` : null;
    store.updated_at = now();
    return structuredClone(store);
  },
  async deleteStore(id: string): Promise<void> {
    await delay(80);
    const index = mockStores.findIndex((x) => x.id === id);
    if (index >= 0) mockStores.splice(index, 1);
    storeProfiles.delete(id);
  },
  async getStoreProfile(id: string): Promise<StoreProfile> {
    await delay(40);
    const profile = storeProfiles.get(id);
    if (!profile) throw new ApiError(404, 'store_not_found', 'Store not found.');
    return { ...profile };
  },
  async updateStoreProfile(id, patch): Promise<StoreProfile> {
    await delay(100);
    const profile = storeProfiles.get(id);
    if (!profile) throw new ApiError(404, 'store_not_found', 'Store not found.');
    const next = { ...profile, ...patch };
    storeProfiles.set(id, next);
    const store = requireStore(id);
    if (patch.niche !== undefined) store.niche = patch.niche;
    if (patch.language !== undefined) store.language = patch.language;
    if (patch.store_name !== undefined) store.shop_name = patch.store_name;
    return { ...next };
  },

  async getAiSettings(): Promise<AiImageSettings> {
    await delay(40);
    return { ...mockAi };
  },
  async updateAiSettings(patch): Promise<AiImageSettings> {
    await delay(100);
    const { api_key, ...rest } = patch;
    mockAi = { ...mockAi, ...rest, has_api_key: api_key ? true : mockAi.has_api_key };
    return { ...mockAi };
  },

  async getThemeLibrary(): Promise<ThemeLibrary> {
    await delay(80);
    return structuredClone(mockThemes);
  },
  async inspectProductCsv(_storeId, content): Promise<ProductCsvInspection> {
    await delay(160);
    const rows = content
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .slice(1);
    const sample: ProductRow[] = rows.slice(0, 5).map((line, index) => {
      const cols = line.split(',');
      return {
        handle: (cols[0] || `product-${index + 1}`).toLowerCase().replace(/\s+/g, '-'),
        title: cols[1] || cols[0] || `Product ${index + 1}`,
        price: cols[2] || '19.00',
        variants: 1 + (index % 3),
      };
    });
    return {
      total: rows.length,
      sample,
      columns_mapped: ['Handle', 'Title', 'Variant Price', 'Image Src'],
      columns_unmapped: [],
    };
  },
  async listCatalogs(): Promise<ProductCatalog[]> {
    await delay(60);
    return structuredClone(mockCatalogs);
  },

  async createBuildPlan(storeId, payload): Promise<BuildPlan> {
    await delay(220);
    const store = requireStore(storeId);
    const theme = themeById(payload.theme_id);
    const catalog =
      payload.product_source === 'catalog'
        ? mockCatalogs.find((c) => c.id === payload.catalog_id)
        : undefined;
    const steps: PlanStep[] = PLAN_STEP_KEYS.map((key) => {
      const cap = CAP_FOR_STEP[key];
      const blocked = cap ? !store.capabilities[cap] : false;
      return {
        key,
        status: blocked ? 'blocked' : 'ready',
        reason: blocked ? `Missing scope for ${key.replace(/_/g, ' ')}` : null,
        error: null,
      };
    });
    const plan: BuildPlan = {
      id: newId('plan'),
      store_id: storeId,
      status: 'staged',
      mode: 'draft_only',
      niche: payload.niche_override || catalog?.niche || store.niche || 'General store',
      language: store.language || 'en',
      theme_name: theme?.name ?? 'Dawn',
      preset: payload.preset,
      product_count: catalog?.product_count ?? store.product_count ?? 0,
      ai_hero: payload.ai_hero && mockAi.enabled,
      steps,
      admin_url: null,
      preview_url: null,
      created_at: now(),
    };
    mockPlans.unshift(plan);
    return structuredClone(plan);
  },
  async getBuildPlan(_storeId, planId): Promise<BuildPlan> {
    await delay(40);
    const plan = requirePlan(planId);
    progressPlan(plan);
    return structuredClone(plan);
  },
  async executeBuildPlan(_storeId, planId, confirm): Promise<BuildPlan> {
    await delay(160);
    const plan = requirePlan(planId);
    if (!confirm) throw new ApiError(422, 'confirm_required', 'Execution must be confirmed.');
    if (plan.status === 'staged' || plan.status === 'failed') {
      plan.status = 'running';
      plan.steps.forEach((step) => {
        if (step.status !== 'blocked') step.status = 'ready';
      });
      planStart.set(plan.id, Date.now());
    }
    return structuredClone(plan);
  },

  async listSessions(limit = 25): Promise<RuntimeSessionRecord[]> {
    await delay(60);
    if (mockSessions.length === 0) {
      const profiles = mockStore.profiles.filter((p) => !p.deleted_at).slice(0, 6);
      profiles.forEach((profile, index) => {
        const startedMs = Date.parse(now()) - (index + 1) * 3_600_000;
        const duration = 300 + index * 220;
        mockSessions.push({
          id: newId('sess'),
          profile_id: profile.id,
          profile_name: profile.name,
          started_at: new Date(startedMs).toISOString(),
          ended_at: new Date(startedMs + duration * 1000).toISOString(),
          duration_seconds: duration,
          startup_ms: 600 + index * 90,
          exit_reason: EXIT_REASONS[index % EXIT_REASONS.length],
        });
      });
    }
    return structuredClone(mockSessions.slice(0, limit));
  },

  async listBackups(): Promise<BackupArchive[]> {
    await delay(60);
    return structuredClone(mockBackups);
  },
  async createBackup(): Promise<BackupArchive> {
    await delay(320);
    const archive: BackupArchive = {
      id: newId('bkp'),
      created_at: now(),
      size_bytes: 2_000_000 + Math.floor(Math.random() * 2_000_000),
      automatic: false,
      verified: true,
      contents: ['profiles', 'proxies', 'workspaces', 'extensions'],
    };
    mockBackups.unshift(archive);
    return structuredClone(archive);
  },
  async restoreBackup(id: string): Promise<void> {
    await delay(400);
    if (!mockBackups.some((b) => b.id === id))
      throw new ApiError(404, 'backup_not_found', 'Backup not found.');
  },
  async deleteBackup(id: string): Promise<void> {
    await delay(80);
    const index = mockBackups.findIndex((b) => b.id === id);
    if (index >= 0) mockBackups.splice(index, 1);
  },

  async getMediaSettings(): Promise<MediaSettings> {
    await delay(40);
    return { ...mockMediaSettings };
  },
  async updateMediaSettings(patch): Promise<MediaSettings> {
    await delay(80);
    mockMediaSettings = { ...mockMediaSettings, ...patch };
    return { ...mockMediaSettings };
  },
  async listMediaAssets(): Promise<MediaAsset[]> {
    await delay(60);
    return structuredClone(mockMediaAssets);
  },
  async createMediaAsset(payload): Promise<MediaAsset> {
    await delay(140);
    const asset: MediaAsset = {
      id: newId('media'),
      name: payload.name,
      kind: payload.kind,
      format: payload.format,
      size_bytes: 100_000 + Math.floor(Math.random() * 4_000_000),
      assigned_profile_count: 0,
      created_at: now(),
    };
    mockMediaAssets.unshift(asset);
    return structuredClone(asset);
  },
  async deleteMediaAsset(id: string): Promise<void> {
    await delay(80);
    const index = mockMediaAssets.findIndex((a) => a.id === id);
    if (index >= 0) mockMediaAssets.splice(index, 1);
    mediaAssignments.delete(id);
  },
  async getMediaAssignments(assetId: string): Promise<string[]> {
    await delay(40);
    return [...(mediaAssignments.get(assetId) ?? [])];
  },
  async setMediaAssignments(assetId, profileIds): Promise<MediaAsset> {
    await delay(120);
    const asset = mockMediaAssets.find((a) => a.id === assetId);
    if (!asset) throw new ApiError(404, 'media_not_found', 'Media asset not found.');
    mediaAssignments.set(assetId, new Set(profileIds));
    asset.assigned_profile_count = profileIds.length;
    return structuredClone(asset);
  },

  async listProxyProviders(): Promise<ProxyProvider[]> {
    await delay(50);
    return structuredClone(mockProxyProviders);
  },
  async configureProxyProvider(payload): Promise<ProxyProvider> {
    await delay(140);
    const provider = mockProxyProviders.find((p) => p.id === payload.provider);
    if (!provider) throw new ApiError(404, 'provider_not_found', 'Provider not found.');
    provider.configured = Boolean(payload.api_token || (payload.username && payload.password));
    return structuredClone(provider);
  },
  async generateProxies(payload): Promise<GenerateProxiesResult> {
    await delay(400);
    const provider = mockProxyProviders.find((p) => p.id === payload.provider);
    if (!provider?.configured)
      throw new ApiError(422, 'provider_not_configured', 'Configure the provider first.');
    const count = Math.max(1, Math.min(50, payload.count));
    const ids: string[] = [];
    for (let index = 0; index < count; index += 1) {
      const host = `${payload.country.toLowerCase()}.residential.${payload.provider}.io`;
      const port = 10000 + Math.floor(Math.random() * 40000);
      const proxy: Proxy = {
        id: newId('px'),
        label: `${provider.name} ${payload.country} ${payload.session_type} #${index + 1}`,
        scheme: 'socks5h',
        host,
        port,
        username: `user-${Math.random().toString(36).slice(2, 8)}`,
        has_password: true,
        masked_endpoint: maskEndpoint('socks5h', host, port, true),
        test_before_launch: false,
        assigned_profile_count: 0,
        exit_ip: null,
        country: payload.country,
        city: null,
        timezone: null,
        asn: null,
        organization: provider.name,
        proxy_type: 'residential',
        type_confidence: 0.95,
        reputation: 'clean',
        latency_ms: null,
        last_checked_at: null,
        created_at: now(),
        updated_at: now(),
      };
      mockStore.proxies.push(proxy);
      ids.push(proxy.id);
    }
    return { created: count, proxy_ids: ids };
  },
};
