export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function apiCall<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = sessionStorage.getItem('plasma_admin_token');
  const res = await fetch(`/admin${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token && { Authorization: `Bearer ${token}` }),
      ...(options.headers || {}),
    },
  });

  // An expired/revoked session bounces back to the sign-in page — but never
  // for the login call itself: reloading on a wrong password silently ate the
  // error and the form appeared to do nothing.
  if ((res.status === 401 || res.status === 403) && path !== '/login') {
    sessionStorage.removeItem('plasma_admin_token');
    window.location.href = '/admin/';
    throw new ApiError(res.status, 'Unauthorized');
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as any;
    // The backend error shape is {"error": "<code>"} (a string).
    const code = typeof body.error === 'string' ? body.error : body.error?.code;
    throw new ApiError(res.status, code || res.statusText);
  }

  return res.status === 204 ? (null as T) : res.json();
}

export const api = {
  login: (email: string, password: string) =>
    apiCall<{ access_token: string; email: string }>('/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  overview: () => apiCall('/overview'),
  users: (query?: string) =>
    apiCall(`/users${query ? `?query=${encodeURIComponent(query)}` : ''}`),
  userDetail: (id: string) => apiCall(`/users/${id}`),
  setUserStatus: (id: string, status: string) =>
    apiCall(`/users/${id}/status`, {
      method: 'POST',
      body: JSON.stringify({ status }),
    }),

  issueKeys: (planId: string, count: number) =>
    apiCall<Array<{ key: string; id: string }>>('/keys', {
      method: 'POST',
      body: JSON.stringify({ plan_id: planId, count }),
    }),
  lookupKeys: (prefix?: string) =>
    apiCall(`/keys${prefix ? `?prefix=${encodeURIComponent(prefix)}` : ''}`),
  revokeKey: (id: string) =>
    apiCall(`/keys/${id}/status`, {
      method: 'POST',
      body: JSON.stringify({ status: 'revoked' }),
    }),

  releaseDevice: (id: string) =>
    apiCall(`/devices/${id}/release`, { method: 'POST' }),

  plans: () => apiCall('/plans'),

  releases: () => apiCall('/releases'),
  publishRelease: (body: any) =>
    apiCall('/releases', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  audit: () => apiCall('/audit'),
};
