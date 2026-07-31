import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import { mockStore } from '@/mocks/store';
import { api } from '@/api';
import type { Proxy } from '@/types/api';
import { ProxyEditorDrawer } from './ProxyEditorDrawer';

beforeEach(() => mockStore.reset());

const EXISTING: Proxy = {
  id: 'px-1',
  label: '02',
  scheme: 'socks5',
  host: '103.82.27.148',
  port: 17735,
  username: '4v7s',
  password: '4v7s',
  has_password: true,
  test_before_launch: true,
  assigned_profile_count: 0,
} as unknown as Proxy;

// Mirrors the profile flow: the drawer is mounted closed, then opened with the
// profile name as defaultLabel.
function Harness({ label }: { label: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>open</button>
      <ProxyEditorDrawer
        open={open}
        proxy={null}
        defaultLabel={label}
        onClose={() => setOpen(false)}
      />
    </>
  );
}

describe('ProxyEditorDrawer defaultLabel', () => {
  it('pre-fills the label with defaultLabel when opened for a new proxy', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness label="Marketplace US 01" />);
    await user.click(screen.getByRole('button', { name: 'open' }));
    const labelInput = await screen.findByPlaceholderText(/residential/i);
    expect(labelInput).toHaveValue('Marketplace US 01');
  });

  it('quick-tests typed values before the proxy is saved', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness label="Marketplace US 01" />);
    await user.click(screen.getByRole('button', { name: 'open' }));

    const quick = await screen.findByRole('button', { name: /quick test/i });
    expect(quick).toBeDisabled(); // no host/port yet

    // Paste fills host/port/creds; label is already prefilled → form is valid.
    await user.type(
      screen.getByPlaceholderText(/socks5h:\/\//i),
      'socks5://user:pass@1.2.3.4:1080',
    );
    await waitFor(() => expect(quick).toBeEnabled());

    await user.click(quick);
    await waitFor(() => expect(screen.getByText(/reachable/i)).toBeInTheDocument());
  });
});

describe('ProxyEditorDrawer test result persistence', () => {
  // Regression: opening from the profile editor passes `proxy={proxies.find(...)}`.
  // The post-test invalidation refetches the list, handing the drawer a NEW proxy
  // object with the SAME id — which used to re-fire the reset effect and wipe the
  // just-shown result ("runs then shows nothing").
  function EditHarness() {
    const [proxy, setProxy] = useState<Proxy>(EXISTING);
    return (
      <>
        {/* Simulates the ['proxies'] refetch: same id, new object reference. */}
        <button onClick={() => setProxy({ ...proxy })}>refetch</button>
        <ProxyEditorDrawer open proxy={proxy} onClose={() => {}} onRemove={() => {}} />
      </>
    );
  }

  it('keeps the quick-test result when the proxy list refetches (same id)', async () => {
    vi.spyOn(api, 'quickTestProxy').mockResolvedValue({
      ok: true,
      connectivity: true,
      exit_ip: '171.246.123.122',
      exit_ip_matches: true,
      latency_ms: 691,
      country: 'VN',
      country_name: 'Vietnam',
      city: null,
      zip_code: null,
      timezone: null,
      latitude: null,
      longitude: null,
      asn: null,
      organization: null,
      checked_at: new Date().toISOString(),
      error: null,
    } as never);

    const user = userEvent.setup();
    renderWithProviders(<EditHarness />);

    await user.click(await screen.findByRole('button', { name: /quick test/i }));
    await waitFor(() => expect(screen.getByText(/reachable/i)).toBeInTheDocument());

    // A background refetch hands down a new proxy object (same id).
    await user.click(screen.getByRole('button', { name: 'refetch' }));

    // The result must survive the refetch, not be wiped by the reset effect.
    expect(screen.getByText(/reachable/i)).toBeInTheDocument();
  });
});
