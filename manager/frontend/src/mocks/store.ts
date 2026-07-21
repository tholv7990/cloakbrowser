/**
 * In-memory mock backend. Holds mutable copies of the fixtures and exposes an
 * event emitter that mimics the WebSocket contract (§14), so the realtime layer
 * drives the UI in mock mode exactly as against a live backend.
 */
import type {
  DiagnosticRun,
  Extension,
  Folder,
  ProfileRead,
  Proxy,
  ProxyQualityReport,
  Settings,
  Tag,
  WorkflowStatus,
} from '@/types/api';
import type { AppEvent, EventName } from '@/types/events';
import { ApiError } from '@/api/http';
import * as fixtures from './data';

type Listener = (event: AppEvent) => void;

function clone<T>(value: T): T {
  return typeof structuredClone === 'function'
    ? structuredClone(value)
    : (JSON.parse(JSON.stringify(value)) as T);
}

let idCounter = 1000;
export function newId(prefix: string): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `${prefix}-${crypto.randomUUID().slice(0, 8)}`;
  }
  idCounter += 1;
  return `${prefix}-${idCounter}`;
}

interface Owner {
  setupRequired: boolean;
  email: string | null;
  loggedOut: boolean;
}

class MockStore {
  profiles: ProfileRead[] = [];
  proxies: Proxy[] = [];
  folders: Folder[] = [];
  tags: Tag[] = [];
  statuses: WorkflowStatus[] = [];
  extensions: Extension[] = [];
  diagnostics: DiagnosticRun[] = [];
  reports: ProxyQualityReport[] = [];
  settings: Settings = clone(fixtures.settings);
  owner: Owner = { setupRequired: false, email: fixtures.ownerEmail, loggedOut: true };

  private listeners = new Set<Listener>();
  private sequence = 0;

  constructor() {
    this.reset();
  }

  reset(): void {
    this.profiles = clone(fixtures.profiles);
    this.proxies = clone(fixtures.proxies);
    this.folders = clone(fixtures.folders);
    this.tags = clone(fixtures.tags);
    this.statuses = clone(fixtures.workflowStatuses);
    this.extensions = clone(fixtures.extensions);
    this.diagnostics = clone(fixtures.diagnostics);
    this.reports = clone(fixtures.qualityReports);
    this.settings = clone(fixtures.settings);
    this.owner = { setupRequired: false, email: fixtures.ownerEmail, loggedOut: true };
    this.sequence = 0;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit<E extends EventName>(event: E, data: unknown): void {
    this.sequence += 1;
    const envelope = {
      event,
      sequence: this.sequence,
      timestamp: new Date().toISOString(),
      data,
    } as AppEvent;
    for (const listener of this.listeners) listener(envelope);
  }

  requireProfile(id: string): ProfileRead {
    const profile = this.profiles.find((p) => p.id === id);
    if (!profile) throw new ApiError(404, 'profile_not_found', 'That profile no longer exists.');
    return profile;
  }

  requireProxy(id: string): Proxy {
    const proxy = this.proxies.find((p) => p.id === id);
    if (!proxy) throw new ApiError(404, 'proxy_not_found', 'That proxy no longer exists.');
    return proxy;
  }

  recomputeProxyAssignments(): void {
    for (const proxy of this.proxies) {
      proxy.assigned_profile_count = this.profiles.filter(
        (p) => p.proxy_id === proxy.id && !p.deleted_at,
      ).length;
    }
  }

  foldersWithCounts(): Folder[] {
    return this.folders.map((folder) => {
      const inFolder = this.profiles.filter((p) => p.folder_id === folder.id && !p.deleted_at);
      return {
        ...folder,
        profile_count: inFolder.length,
        running_count: inFolder.filter((p) => p.runtime_state === 'running').length,
      };
    });
  }
}

export const mockStore = new MockStore();
