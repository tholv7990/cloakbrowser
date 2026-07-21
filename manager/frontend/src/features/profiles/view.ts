import type {
  ProfileRead,
  ProfileView,
  ProfileWrite,
  Proxy,
  ProxyHealth,
  Tag,
  WorkflowStatus,
} from '@/types/api';
import { defaultWizardValues, wizardValuesToPayload } from '@/schemas/profile';

export interface ProfileCatalog {
  tags: Tag[];
  statuses: WorkflowStatus[];
  proxies: Proxy[];
}

/** Join a normalized ProfileRead against the catalog + runtime message overlay. */
export function toProfileView(
  read: ProfileRead,
  catalog: ProfileCatalog,
  messages: Record<string, string>,
): ProfileView {
  return {
    id: read.id,
    name: read.name,
    pinned: read.pinned,
    folder_id: read.folder_id,
    fingerprint_seed: read.fingerprint_seed,
    tags: read.tag_ids
      .map((id) => catalog.tags.find((t) => t.id === id))
      .filter((t): t is Tag => Boolean(t)),
    notes: read.notes,
    workflow_status: catalog.statuses.find((s) => s.id === read.workflow_status_id) ?? null,
    proxy: read.proxy_id ? (catalog.proxies.find((p) => p.id === read.proxy_id) ?? null) : null,
    runtime_state: read.runtime_state,
    runtime_message: messages[read.id] ?? null,
    last_opened_at: read.last_opened_at,
    browser_version_mode: read.browser_version_mode,
    browser_version: read.browser_version,
    read,
  };
}

export function buildProfileViews(
  items: ProfileRead[],
  catalog: ProfileCatalog,
  messages: Record<string, string>,
): ProfileView[] {
  return items.map((item) => toProfileView(item, catalog, messages));
}

export function proxyHealth(proxy: Proxy): ProxyHealth {
  if (proxy.scheme === 'direct') return 'untested';
  if (proxy.reputation === 'malicious') return 'unreachable';
  if (proxy.reputation === 'suspicious') return 'degraded';
  if (proxy.latency_ms == null) return 'untested';
  return 'healthy';
}

/** Strip read-only fields so a full profile can be re-sent on PATCH (which replaces). */
export function readToWrite(read: ProfileRead): ProfileWrite {
  const {
    id: _id,
    fingerprint_revision: _rev,
    fingerprint_config_hash: _hash,
    runtime_state: _state,
    created_at: _created,
    updated_at: _updated,
    last_opened_at: _opened,
    total_runtime_seconds: _runtime,
    deleted_at: _deleted,
    ...write
  } = read;
  return write;
}

/** Minimal valid ProfileCreate body for quick-create. */
export function emptyProfileWrite(name: string): ProfileWrite {
  return wizardValuesToPayload(defaultWizardValues({ name }));
}
