/**
 * Environment-configurable API/WS wiring + the in-memory CSRF token.
 *
 * Auth model (spec §3): the dashboard authenticates with an HttpOnly,
 * SameSite=Strict session cookie the browser sends automatically. JavaScript
 * never sees the session token or the internal per-install bootstrap secret.
 * Mutating requests carry a session-bound `X-CSRF-Token` header, whose value
 * comes from `GET /auth/session` and is held here (memory only, never persisted).
 */

const injected = typeof window !== 'undefined' ? window.__CLOAKBROWSER__ : undefined;

const defaultApiMode: 'mock' | 'real' = import.meta.env.MODE === 'test' ? 'mock' : 'real';
export const API_MODE: 'mock' | 'real' = import.meta.env.VITE_API_MODE ?? defaultApiMode;

export const API_BASE_URL: string = (
  injected?.apiBaseUrl ??
  import.meta.env.VITE_API_BASE_URL ??
  '/api/v1'
).replace(/\/$/, '');

/** Resolve a relative base (e.g. "/api/v1") against the page origin so a
 * same-origin dev proxy — and production static serving — both work. */
export function absoluteApiBase(): string {
  if (API_BASE_URL.startsWith('http')) return API_BASE_URL;
  if (typeof window !== 'undefined') return `${window.location.origin}${API_BASE_URL}`;
  return API_BASE_URL;
}

/** Resolve only backend-issued API routes; local filesystem paths are never accepted. */
export function absoluteApiResource(path: string): string {
  if (!path.startsWith('/api/v1/')) return '';
  const base = absoluteApiBase();
  if (base.startsWith('http')) return new URL(path, base).toString();
  return path;
}

function deriveWsUrl(): string {
  if (injected?.wsUrl) return injected.wsUrl;
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL;
  return `${absoluteApiBase().replace(/^http/, 'ws')}/events`;
}

export const WS_URL: string = deriveWsUrl();

/** Per-process local API token injected by the desktop shell (packaged builds).
 * Absent in the browser dev workflow, where the loopback token gate is off. Sent as
 * an `Authorization: Bearer` header; never persisted or logged. */
export const LOCAL_TOKEN: string | null = injected?.token ?? null;

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}
