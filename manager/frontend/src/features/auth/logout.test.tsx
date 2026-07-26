import { describe, expect, it, vi } from 'vitest';
import { render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from '@/api';
import { AuthGate } from './AuthGate';
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

  it('lands back on the login screen after signing out', async () => {
    vi.spyOn(api, 'authStatus').mockResolvedValue({ setup_required: false });
    vi.spyOn(api, 'authSession')
      .mockResolvedValueOnce({ email: 'o@example.com', csrf_token: 'c' })
      .mockRejectedValue(new Error('authentication_required'));
    vi.spyOn(api, 'authLogout').mockResolvedValue({ ok: true });

    function SignOutProbe() {
      const logout = useLogout();
      return <button onClick={() => logout.mutate()}>probe-signout</button>;
    }

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <AuthGate>
          <SignOutProbe />
        </AuthGate>
      </QueryClientProvider>,
    );

    await userEvent.click(await screen.findByText('probe-signout'));
    // Regression: queryClient.clear() empties the cache without notifying
    // mounted observers, so AuthGate never re-rendered and the app stayed
    // on the signed-in page.
    expect(
      await screen.findByRole('heading', { name: /^sign in$/i }),
    ).toBeInTheDocument();
  });
});
