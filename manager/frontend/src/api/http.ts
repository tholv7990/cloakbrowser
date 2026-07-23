/**
 * Thin typed fetch wrapper. Adds the local token to mutations + the WebSocket
 * handshake, enforces JSON content types, and normalizes the spec error
 * envelope (§13) into a thrown ApiError the UI can render safely.
 */
import type { ApiErrorBody, DownloadFile } from '@/types/api';
import { LOCAL_TOKEN, absoluteApiBase, getCsrfToken } from './config';

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly fieldErrors: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    fieldErrors: Record<string, unknown> = {},
    requestId: string | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.fieldErrors = fieldErrors;
    this.requestId = requestId;
  }
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

interface RequestOptions {
  method?: Method;
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = new URL(`${absoluteApiBase()}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

function requestHeaders(method: Method, hasBody: boolean): Record<string, string> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (hasBody) headers['Content-Type'] = 'application/json';
  // Packaged desktop: prove this request comes from the shell, not another local
  // process. Absent in dev, where the backend's token gate is off.
  if (LOCAL_TOKEN) headers['Authorization'] = `Bearer ${LOCAL_TOKEN}`;
  if (method !== 'GET') {
    const csrf = getCsrfToken();
    if (csrf) headers['X-CSRF-Token'] = csrf;
  }
  return headers;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, signal } = options;
  const headers = requestHeaders(method, body !== undefined);

  // Mutations carry the session-bound CSRF token (§3). The session itself rides
  // an HttpOnly cookie the browser attaches automatically (credentials).
  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      credentials: 'include',
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (cause) {
    throw new ApiError(0, 'network_error', 'Cannot reach the manager backend.', {}, null);
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload = text ? safeJson(text) : undefined;

  if (!response.ok) {
    const envelope = payload as ApiErrorBody | undefined;
    const err = envelope?.error;
    throw new ApiError(
      response.status,
      err?.code ?? 'request_failed',
      err?.message ?? `Request failed (${response.status}).`,
      err?.field_errors ?? {},
      err?.request_id ?? null,
    );
  }

  return payload as T;
}

export async function apiDownload(
  path: string,
  options: Pick<RequestOptions, 'query' | 'signal'> = {},
): Promise<DownloadFile> {
  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method: 'GET',
      headers: requestHeaders('GET', false),
      credentials: 'include',
      signal: options.signal,
    });
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the manager backend.', {}, null);
  }
  if (!response.ok) {
    const text = await response.text();
    const envelope = (text ? safeJson(text) : undefined) as ApiErrorBody | undefined;
    const err = envelope?.error;
    throw new ApiError(
      response.status,
      err?.code ?? 'request_failed',
      err?.message ?? `Request failed (${response.status}).`,
      err?.field_errors ?? {},
      err?.request_id ?? null,
    );
  }
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const filename = disposition.match(/filename="([^"\r\n]+)"/i)?.[1] ?? 'download';
  return { blob: await response.blob(), filename };
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}
