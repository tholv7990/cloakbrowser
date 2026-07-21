/** Mock backend adapter. Fully exercises the UI without a live server. */
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
  ParsedProxy,
  ProfileCreatePayload,
  ProfileListParams,
  ProfileLogs,
  ProfileRead,
  ProfileUpdatePayload,
  Proxy,
  ProxyQualityReport,
  ProxyQuickTest,
  ProxyScheme,
  ProxyWritePayload,
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
  return {
    id: newId('prof'),
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
      country: 'United States',
      city: 'Local network',
      timezone: 'America/New_York',
      asn: 'AS64500',
      organization: 'Direct connection',
      checked_at: now(),
      error: null,
    };
  }
  const reachable = proxy.reputation !== 'malicious';
  return {
    ok: reachable,
    connectivity: reachable,
    exit_ip: proxy.exit_ip ?? '203.0.113.10',
    exit_ip_matches: reachable,
    latency_ms: proxy.latency_ms ?? 180,
    country: proxy.country,
    city: proxy.city,
    timezone: proxy.timezone,
    asn: proxy.asn,
    organization: proxy.organization,
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
      },
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
    Object.assign(profile, payload, { updated_at: now() });
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

  async getProfileLogs(id: string): Promise<ProfileLogs> {
    await delay(120);
    const profile = mockStore.requireProfile(id);
    return {
      profile_id: id,
      entries: [
        {
          timestamp: '2026-07-21T09:00:00Z',
          level: 'info',
          message: 'Manager acquired profile lock.',
        },
        {
          timestamp: '2026-07-21T09:00:01Z',
          level: 'info',
          message: `Preset ${profile.fingerprint_preset}, seed ${profile.fingerprint_seed}.`,
        },
        {
          timestamp: '2026-07-21T09:00:02Z',
          level: 'info',
          message: 'Proxy pre-launch test passed (median 148 ms).',
        },
        {
          timestamp: '2026-07-21T09:00:03Z',
          level: 'info',
          message: 'Launched persistent context; browser ready.',
        },
        ...(profile.runtime_state === 'crashed'
          ? [
              {
                timestamp: '2026-07-21T09:05:00Z',
                level: 'error' as const,
                message: 'Browser process exited unexpectedly (code 1).',
              },
            ]
          : []),
      ],
    };
  },

  async exportProfile(id: string): Promise<Record<string, unknown>> {
    await delay(120);
    const p = mockStore.requireProfile(id);
    const proxy = p.proxy_id ? mockStore.proxies.find((x) => x.id === p.proxy_id) : null;
    return {
      schema_version: 2,
      profile: {
        name: p.name,
        fingerprint_preset: p.fingerprint_preset,
        fingerprint_seed: p.fingerprint_seed,
        browser_version_mode: p.browser_version_mode,
        browser_version: p.browser_version,
        user_agent_mode: p.user_agent_mode,
        startup_urls: p.startup_urls,
        location: p.location,
        window: p.window,
        behavior: p.behavior,
        proxy: proxy
          ? { label: proxy.label, scheme: proxy.scheme, masked_endpoint: proxy.masked_endpoint }
          : null,
      },
    };
  },

  async importProfile(payload: Record<string, unknown>): Promise<ProfileRead> {
    await delay(200);
    const source = (payload.profile ?? payload) as Record<string, unknown>;
    const name =
      typeof source.name === 'string' && source.name
        ? `${source.name}-imported`
        : 'imported-profile';
    const profile = buildProfile({}, name);
    mockStore.profiles.unshift(profile);
    mockStore.emit('profile.created', { profile: structuredClone(profile) });
    return structuredClone(profile);
  },

  async importCookies(id: string, payload: CookieImportPayload): Promise<CookieImportResult> {
    await delay(220);
    mockStore.requireProfile(id);
    const lines = payload.content.split('\n').filter((l) => l.trim() && !l.startsWith('#'));
    const imported = Math.max(1, lines.length);
    return {
      imported_count: imported,
      skipped_count: 0,
      format: payload.format,
      warnings: imported > 200 ? ['Large cookie set; some entries may be session-only.'] : [],
    };
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
    mockStore.diagnostics.unshift({
      id: newId('diag'),
      kind: 'proxy_quality',
      proxy_id: id,
      profile_id: null,
      state: 'completed',
      summary: `${proxy.label} — ${report.reputation ?? 'unknown'}, Turnstile ${report.turnstile_outcome}.`,
      artifact_path: report.report_path,
      created_at: report.checked_at,
      updated_at: report.checked_at,
    });
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
  async listDiagnostics(): Promise<DiagnosticRun[]> {
    await delay(120);
    return structuredClone(mockStore.diagnostics);
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
      proxy_id: null,
      profile_id: null,
      state: 'completed',
      summary: 'Direct-network Google control reachable; no challenge.',
      artifact_path: null,
      created_at: now(),
      updated_at: now(),
    };
    mockStore.diagnostics.unshift(diag);
    mockStore.emit('diagnostic.completed', { diagnostic_id: diag.id, state: 'completed' });
    return structuredClone(diag);
  },
  async runPixelscan(profileId: string): Promise<DiagnosticRun> {
    await delay(500);
    const diag: DiagnosticRun = {
      id: newId('diag'),
      kind: 'pixelscan',
      proxy_id: null,
      profile_id: profileId,
      state: 'completed',
      summary: 'Pixelscan regression completed; consistency score nominal.',
      artifact_path: `reports/pixelscan/${profileId}.json`,
      created_at: now(),
      updated_at: now(),
    };
    mockStore.diagnostics.unshift(diag);
    mockStore.emit('diagnostic.completed', { diagnostic_id: diag.id, state: 'completed' });
    return structuredClone(diag);
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
};
