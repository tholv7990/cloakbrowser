// Reusable profile templates for fast creation (BitBrowser/Hidemium-style): a
// saved snapshot of the create form (minus the name) that pre-fills a new profile.
// Stored locally — this manager is a single-user app on loopback.
import type { ProfileWizardValues } from '@/schemas/profile';

export interface ProfileTemplate {
  id: string;
  name: string;
  config: Partial<ProfileWizardValues>;
  createdAt: number;
}

const KEY = 'cb.profileTemplates';

/** Always-present, non-deletable starting point: the best privacy defaults so a
 *  profile leaks nothing (geo + WebRTC from the proxy, consistent fingerprint,
 *  camera/mic/notifications blocked). Its id is prefixed `builtin:`. */
export const BUILTIN_TEMPLATES: ProfileTemplate[] = [
  {
    id: 'builtin:no-leak',
    name: 'Recommended · No-leak',
    createdAt: 0,
    config: {
      geo_mode: 'proxy',
      webrtc_mode: 'proxy',
      geolocation_mode: 'ask',
      fingerprint_preset: 'consistent',
      test_proxy_before_launch: true,
      permission_notifications: 'block',
      permission_camera: 'block',
      permission_microphone: 'block',
      hardware_concurrency_mode: 'automatic',
      gpu_mode: 'automatic',
    },
  },
];

export function isBuiltinTemplate(id: string): boolean {
  return id.startsWith('builtin:');
}

function readUserTemplates(): ProfileTemplate[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? '[]');
    return Array.isArray(raw) ? (raw as ProfileTemplate[]) : [];
  } catch {
    return [];
  }
}

export function listTemplates(): ProfileTemplate[] {
  return [...BUILTIN_TEMPLATES, ...readUserTemplates()];
}

function persist(templates: ProfileTemplate[]): void {
  localStorage.setItem(KEY, JSON.stringify(templates));
}

/** Save the current form values (name excluded) as a named template. */
export function saveTemplate(name: string, values: ProfileWizardValues): ProfileTemplate {
  const { name: _drop, ...config } = values;
  const template: ProfileTemplate = {
    id: crypto.randomUUID(),
    name: name.trim(),
    config,
    createdAt: Date.now(),
  };
  // Replace an existing template with the same name so re-saving updates it.
  const others = readUserTemplates().filter((t) => t.name !== template.name);
  persist([template, ...others]);
  return template;
}

export function deleteTemplate(id: string): void {
  if (isBuiltinTemplate(id)) return; // built-ins are permanent
  persist(readUserTemplates().filter((t) => t.id !== id));
}
