import { z } from 'zod';
import type { ProfileRead, ProfileUpdatePayload, ProfileWrite } from '@/types/api';

const VERSION_RE = /^[0-9]+(?:\.[0-9]+){3,4}$/;
const URL_SCHEME_RE = /^(https?|chrome-extension):\/\//i;

const permission = z.enum(['ask', 'allow', 'block']);

/**
 * Flat wizard form values. Numeric fields are kept as strings to avoid coercion
 * surprises; the payload builder parses them and applies the backend's
 * mode-conditional rules (e.g. coordinates only in manual geolocation).
 */
export const profileWizardSchema = z
  .object({
    // Step 1 — General
    name: z.string().trim().min(1, 'Name is required.').max(80),
    folder_id: z.string(),
    workflow_status_id: z.string(),
    tag_ids: z.array(z.string()),
    notes: z.string().max(4000, 'Notes are limited to 4,000 characters.'),
    startup_urls_text: z.string().max(4000),

    // Step 2 — Proxy and location
    proxy_id: z.string(),
    test_proxy_before_launch: z.boolean(),
    geo_mode: z.enum(['proxy', 'manual', 'system']),
    locale: z.string().trim().max(35),
    timezone: z.string().trim().max(60),
    webrtc_mode: z.enum(['proxy', 'direct']),
    geolocation_mode: z.enum(['proxy', 'manual', 'ask', 'block']),
    latitude: z.string(),
    longitude: z.string(),
    accuracy: z.string(),

    // Step 3 — Browser identity
    fingerprint_preset: z.enum(['default', 'consistent']),
    fingerprint_seed: z.string().regex(/^\d+$/, 'Seed must be numeric.'),
    browser_version_mode: z.enum(['installed', 'pinned']),
    browser_version: z.string().trim(),
    user_agent_mode: z.enum(['automatic', 'custom']),
    custom_user_agent: z.string().trim(),

    // Step 4 — Window and appearance
    window_mode: z.enum(['maximized', 'custom']),
    window_width: z.string(),
    window_height: z.string(),

    // Step 6 — Extensions (not part of ProfileCreate yet; see contract questions)
    extension_ids: z.array(z.string()),

    // Step 7 — Advanced behavior (F-006: only permissions remain applied at launch)
    permission_geolocation: permission,
    permission_notifications: permission,
    permission_camera: permission,
    permission_microphone: permission,
    permission_clipboard: permission,
  })
  .superRefine((v, ctx) => {
    const add = (path: string, message: string) =>
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: [path], message });

    if (v.browser_version_mode === 'pinned' && !VERSION_RE.test(v.browser_version)) {
      add('browser_version', 'Enter a full numeric version, e.g. 146.0.7680.177.');
    }
    if (v.user_agent_mode === 'custom' && v.custom_user_agent.trim().length < 20) {
      add('custom_user_agent', 'Enter the full custom user-agent string.');
    }
    if (v.window_mode === 'custom') {
      if (!v.window_width) add('window_width', 'Width is required in custom mode.');
      if (!v.window_height) add('window_height', 'Height is required in custom mode.');
    }
    if (v.geolocation_mode === 'manual') {
      if (!v.latitude) add('latitude', 'Latitude is required for manual geolocation.');
      if (!v.longitude) add('longitude', 'Longitude is required for manual geolocation.');
    }
    for (const line of v.startup_urls_text
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean)) {
      if (!URL_SCHEME_RE.test(line)) {
        add('startup_urls_text', 'Startup URLs must be http, https, or chrome-extension.');
        break;
      }
    }
  });

export type ProfileWizardValues = z.infer<typeof profileWizardSchema>;

/** Fields validated on each wizard step (used to gate Next). */
export const stepFields: Record<number, (keyof ProfileWizardValues)[]> = {
  0: ['name', 'notes', 'startup_urls_text'],
  1: ['locale', 'timezone', 'latitude', 'longitude'],
  2: ['fingerprint_seed', 'browser_version', 'custom_user_agent'],
  3: ['window_width', 'window_height'],
  4: [],
  5: [],
  6: [],
  7: [],
};

const numOrNull = (value: string): number | null => {
  const n = Number(value);
  return value.trim() === '' || Number.isNaN(n) ? null : n;
};

/** A cryptographically strong, full 64-bit unsigned decimal seed (F-007). The
 * backend accepts up to 2^64-1; Math.random gives only 32 non-crypto bits. */
export function randomSeed(): string {
  const parts = crypto.getRandomValues(new Uint32Array(2));
  return ((BigInt(parts[0]) << 32n) | BigInt(parts[1])).toString();
}

export function defaultWizardValues(overrides?: Partial<ProfileWizardValues>): ProfileWizardValues {
  return {
    name: '',
    folder_id: '',
    workflow_status_id: '',
    tag_ids: [],
    notes: '',
    startup_urls_text: '',
    proxy_id: '',
    test_proxy_before_launch: true,
    geo_mode: 'proxy',
    locale: 'en-US',
    timezone: 'America/New_York',
    webrtc_mode: 'proxy',
    geolocation_mode: 'ask',
    latitude: '',
    longitude: '',
    accuracy: '',
    fingerprint_preset: 'consistent',
    fingerprint_seed: randomSeed(),
    browser_version_mode: 'installed',
    browser_version: '',
    user_agent_mode: 'automatic',
    custom_user_agent: '',
    window_mode: 'maximized',
    window_width: '',
    window_height: '',
    extension_ids: [],
    permission_geolocation: 'ask',
    permission_notifications: 'block',
    permission_camera: 'block',
    permission_microphone: 'block',
    permission_clipboard: 'ask',
    ...overrides,
  };
}

export function profileToWizardValues(
  p: ProfileRead,
  extensionIds: string[] = [],
): ProfileWizardValues {
  const str = (value: number | null): string => (value == null ? '' : String(value));
  return {
    name: p.name,
    folder_id: p.folder_id ?? '',
    workflow_status_id: p.workflow_status_id ?? '',
    tag_ids: p.tag_ids,
    notes: p.notes,
    startup_urls_text: p.startup_urls.join('\n'),
    proxy_id: p.proxy_id ?? '',
    test_proxy_before_launch: p.test_proxy_before_launch,
    geo_mode: p.location.geo_mode,
    locale: p.location.locale ?? '',
    timezone: p.location.timezone ?? '',
    webrtc_mode: p.location.webrtc_mode,
    geolocation_mode: p.location.geolocation_mode,
    latitude: str(p.location.latitude),
    longitude: str(p.location.longitude),
    accuracy: str(p.location.accuracy),
    fingerprint_preset: p.fingerprint_preset,
    fingerprint_seed: p.fingerprint_seed,
    browser_version_mode: p.browser_version_mode,
    browser_version: p.browser_version ?? '',
    user_agent_mode: p.user_agent_mode,
    custom_user_agent: p.custom_user_agent ?? '',
    window_mode: p.window.mode,
    window_width: str(p.window.width),
    window_height: str(p.window.height),
    extension_ids: [...extensionIds],
    permission_geolocation: p.behavior.permissions.geolocation ?? 'ask',
    permission_notifications: p.behavior.permissions.notifications ?? 'block',
    permission_camera: p.behavior.permissions.camera ?? 'block',
    permission_microphone: p.behavior.permissions.microphone ?? 'block',
    permission_clipboard: p.behavior.permissions.clipboard ?? 'ask',
  };
}

export function wizardValuesToPayload(v: ProfileWizardValues): ProfileWrite {
  const manual = v.geolocation_mode === 'manual';
  const custom = v.window_mode === 'custom';
  return {
    name: v.name.trim(),
    folder_id: v.folder_id || null,
    workflow_status_id: v.workflow_status_id || null,
    tag_ids: v.tag_ids,
    notes: v.notes,
    pinned: false,
    startup_urls: v.startup_urls_text
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean),
    fingerprint_seed: v.fingerprint_seed,
    fingerprint_preset: v.fingerprint_preset,
    browser_version_mode: v.browser_version_mode,
    browser_version: v.browser_version_mode === 'pinned' ? v.browser_version.trim() : null,
    user_agent_mode: v.user_agent_mode,
    custom_user_agent: v.user_agent_mode === 'custom' ? v.custom_user_agent.trim() : null,
    location: {
      geo_mode: v.geo_mode,
      locale: v.locale.trim() || null,
      timezone: v.timezone.trim() || null,
      webrtc_mode: v.webrtc_mode,
      geolocation_mode: v.geolocation_mode,
      latitude: manual ? numOrNull(v.latitude) : null,
      longitude: manual ? numOrNull(v.longitude) : null,
      accuracy: manual ? numOrNull(v.accuracy) : null,
    },
    window: {
      mode: v.window_mode,
      width: custom ? numOrNull(v.window_width) : null,
      height: custom ? numOrNull(v.window_height) : null,
    },
    behavior: {
      permissions: {
        geolocation: v.permission_geolocation,
        notifications: v.permission_notifications,
        camera: v.permission_camera,
        microphone: v.permission_microphone,
        clipboard: v.permission_clipboard,
      },
    },
    proxy_id: v.proxy_id || null,
    test_proxy_before_launch: v.test_proxy_before_launch,
  };
}

const PATCHABLE_PROFILE_KEYS: (keyof Omit<ProfileWrite, 'fingerprint_seed'>)[] = [
  'name',
  'folder_id',
  'workflow_status_id',
  'tag_ids',
  'notes',
  'pinned',
  'startup_urls',
  'fingerprint_preset',
  'browser_version_mode',
  'browser_version',
  'user_agent_mode',
  'custom_user_agent',
  'location',
  'window',
  'behavior',
  'proxy_id',
  'test_proxy_before_launch',
];

function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

/** Build an optimistic-concurrency PATCH by diffing against the profile loaded
 * into the editor. Read-only identity fields and unchanged values are omitted. */
export function wizardValuesToPatch(
  values: ProfileWizardValues,
  loaded: ProfileRead,
): ProfileUpdatePayload {
  const candidate = { ...wizardValuesToPayload(values), pinned: loaded.pinned };
  const baseline = {
    ...wizardValuesToPayload(profileToWizardValues(loaded)),
    pinned: loaded.pinned,
  };
  const changed: Partial<Omit<ProfileWrite, 'fingerprint_seed'>> = {};
  for (const key of PATCHABLE_PROFILE_KEYS) {
    if (!sameValue(candidate[key], baseline[key])) {
      Object.assign(changed, { [key]: candidate[key] });
    }
  }
  return { expected_updated_at: loaded.updated_at, ...changed };
}
