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

export const API_MODE: 'mock' | 'real' = import.meta.env.VITE_API_MODE ?? 'mock';

export const API_BASE_URL: string = (
  injected?.apiBaseUrl ??
  import.meta.env.VITE_API_BASE_URL ??
  'http://127.0.0.1:8799/api/v1'
).replace(/\/$/, '');

function deriveWsUrl(): string {
  if (injected?.wsUrl) return injected.wsUrl;
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL;
  const httpBase = API_BASE_URL.replace(/^http/, 'ws');
  return `${httpBase}/events`;
}

export const WS_URL: string = deriveWsUrl();

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}
