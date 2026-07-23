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

export function listTemplates(): ProfileTemplate[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? '[]');
    return Array.isArray(raw) ? (raw as ProfileTemplate[]) : [];
  } catch {
    return [];
  }
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
  const others = listTemplates().filter((t) => t.name !== template.name);
  persist([template, ...others]);
  return template;
}

export function deleteTemplate(id: string): void {
  persist(listTemplates().filter((t) => t.id !== id));
}
