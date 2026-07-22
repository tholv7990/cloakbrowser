/**
 * Typed WebSocket event contract (spec §14).
 *
 * The envelope shape is fixed by the spec. Per-event `data` payloads are not
 * enumerated in the spec, so the shapes below are documented assumptions (see
 * docs/frontend-backend-contract-questions.md). Events are treated as
 * invalidation/status signals; on reconnect the client refetches server state.
 */
import type { DiagnosticKind, DiagnosticStatus, Proxy, ProfileRead, RuntimeState } from './api';

export type EventName =
  | 'profile.created'
  | 'profile.updated'
  | 'profile.deleted'
  | 'profile.runtime.changed'
  | 'profile.runtime.message'
  | 'runtime.snapshot'
  | 'proxy.updated'
  | 'proxy.test.progress'
  | 'proxy.test.completed'
  | 'diagnostic.progress'
  | 'diagnostic.completed'
  | 'manager.reconciliation.completed';

export interface EventEnvelope<E extends EventName = EventName, D = unknown> {
  event: E;
  sequence: number;
  timestamp: string;
  data: D;
}

export interface ProfileCreatedData {
  profile: ProfileRead;
}
export interface ProfileUpdatedData {
  profile: ProfileRead;
}
export interface ProfileDeletedData {
  profile_id: string;
}
export interface ProfileRuntimeChangedData {
  profile_id: string;
  runtime_state: RuntimeState;
  message?: string | null;
}
export interface ProfileRuntimeMessageData {
  profile_id: string;
  message: string;
  level: 'info' | 'warning' | 'error';
  state?: RuntimeState;
}
export interface ProxyUpdatedData {
  proxy: Proxy;
}
export interface ProxyTestProgressData {
  proxy_id: string;
  kind: 'quick' | 'quality';
  phase: string;
  progress: number;
  message: string;
}
export interface ProxyTestCompletedData {
  proxy_id: string;
  kind: 'quick' | 'quality';
  ok: boolean;
  report_id: string | null;
}
export interface DiagnosticProgressData {
  diagnostic_id: string;
  profile_id: string | null;
  kind: DiagnosticKind;
  status: DiagnosticStatus;
  progress: number;
  error_code: string | null;
}
export type DiagnosticCompletedData = DiagnosticProgressData;
export interface ReconciliationCompletedData {
  changed_profile_ids: string[];
}

/** Backend runtime snapshot (spec §14 real WS): the full set of owned sessions,
 * re-sent whenever any changes. `state` uses the backend vocabulary. */
export interface RuntimeSnapshotData {
  runtimes: { profile_id: string; state: string; last_message: string | null }[];
  running_session_count: number;
}

export type AppEvent =
  | EventEnvelope<'profile.created', ProfileCreatedData>
  | EventEnvelope<'profile.updated', ProfileUpdatedData>
  | EventEnvelope<'profile.deleted', ProfileDeletedData>
  | EventEnvelope<'profile.runtime.changed', ProfileRuntimeChangedData>
  | EventEnvelope<'profile.runtime.message', ProfileRuntimeMessageData>
  | EventEnvelope<'proxy.updated', ProxyUpdatedData>
  | EventEnvelope<'proxy.test.progress', ProxyTestProgressData>
  | EventEnvelope<'proxy.test.completed', ProxyTestCompletedData>
  | EventEnvelope<'diagnostic.progress', DiagnosticProgressData>
  | EventEnvelope<'diagnostic.completed', DiagnosticCompletedData>
  | EventEnvelope<'manager.reconciliation.completed', ReconciliationCompletedData>
  | EventEnvelope<'runtime.snapshot', RuntimeSnapshotData>;

export type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';
