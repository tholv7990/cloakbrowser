import { describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from '@/api';
import { useLogout } from './api';

function harness() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(['auth', 'session'], { email: 'o@example.com', csrf_token: 'c' });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

describe('useLogout', () => {
  it('clears the local session when the server logout succeeds', async () => {
    vi.spyOn(api, 'authLogout').mockResolvedValue({ ok: true });
    const { client, wrapper } = harness();
    const { result } = renderHook(() => useLogout(), { wrapper });
    result.current.mutate();
    await waitFor(() =>
      expect(client.getQueryData(['auth', 'session'])).toBeUndefined(),
    );
  });

  it('still signs out locally when the server call fails', async () => {
    // An already-expired session makes logout itself 401. Clearing only on
    // success stranded the user on a page that looked signed in.
    vi.spyOn(api, 'authLogout').mockRejectedValue(new Error('authentication_required'));
    const { client, wrapper } = harness();
    const { result } = renderHook(() => useLogout(), { wrapper });
    result.current.mutate();
    await waitFor(() =>
      expect(client.getQueryData(['auth', 'session'])).toBeUndefined(),
    );
  });
});
