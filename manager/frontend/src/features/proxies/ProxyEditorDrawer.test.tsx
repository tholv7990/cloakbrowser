import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import { mockStore } from '@/mocks/store';
import { api } from '@/api';
import type { Proxy, ProxyQualityReport } from '@/types/api';
import { ProxyEditorDrawer } from './ProxyEditorDrawer';

beforeEach(() => {
  vi.restoreAllMocks();
  mockStore.reset();
});

const EXISTING: Proxy = {
  id: 'px-1',
  label: '02',
  scheme: 'socks5',
  host: '103.82.27.148',
  port: 17735,
  username: '4v7s',
  has_password: true,
  test_before_launch: true,
  assigned_profile_count: 0,
  masked_endpoint: 'socks5://103.82.27.148:17735',
  exit_ip: null,
  country: null,
  city: null,
  timezone: null,
  asn: null,
  organization: null,
  proxy_type: null,
  type_confidence: null,
  reputation: null,
  latency_ms: null,
  last_checked_at: null,
  created_at: '2026-08-02T00:00:00.000Z',
  updated_at: '2026-08-02T00:00:00.000Z',
};

const QUALITY_RESULT: ProxyQualityReport = {
  id: 'report-1',
  proxy_id: 'px-1',
  state: 'completed',
  proxy_type: null,
  type_confidence: null,
  reputation: null,
  matched_lists: [],
  google_outcome: null,
  turnstile_outcome: null,
  alignment: {
    http: { status: 'unknown', detail: 'Not checked' },
    webrtc: { status: 'unknown', detail: 'Not checked' },
    dns: { status: 'unknown', detail: 'Not checked' },
    timezone: { status: 'unknown', detail: 'Not checked' },
    locale: { status: 'unknown', detail: 'Not checked' },
  },
  latency_ms: null,
  exit_ip: null,
  country: null,
  city: null,
  timezone: null,
  asn: null,
  organization: null,
  screenshot_path: null,
  report_path: null,
  observed_scope: 'test',
  checked_at: '2026-08-02T00:00:00.000Z',
};

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

function CreateRefetchHarness() {
  const [proxy, setProxy] = useState<Proxy | null>(null);
  return (
    <ProxyEditorDrawer
      open
      proxy={proxy}
      defaultLabel="New proxy"
      onClose={() => {}}
      onSaved={setProxy}
    />
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

  it('switches the standalone catalog title to edit after creation', async () => {
    const created = { ...EXISTING, id: 'px-standalone-created' };
    vi.spyOn(api, 'createProxy').mockResolvedValue(created);
    const user = userEvent.setup();
    renderWithProviders(
      <ProxyEditorDrawer open proxy={null} defaultLabel="Standalone" onClose={() => {}} />,
    );

    await user.type(
      await screen.findByPlaceholderText(/socks5h:\/\//i),
      'socks5://user:pass@198.51.100.9:1080',
    );
    await user.click(screen.getByRole('button', { name: /create proxy/i }));

    expect(await screen.findByRole('dialog', { name: /edit proxy/i })).toBeInTheDocument();
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
    const quickAdhoc = vi.spyOn(api, 'quickTestProxyAdhoc').mockResolvedValue({
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
    expect(quickAdhoc).toHaveBeenCalledWith({
      scheme: 'socks5',
      host: '103.82.27.148',
      port: 17735,
      username: '4v7s',
      password: null,
      credential_proxy_id: EXISTING.id,
    });

    // A background refetch hands down a new proxy object (same id).
    await user.click(screen.getByRole('button', { name: 'refetch' }));

    // The result must survive the refetch, not be wiped by the reset effect.
    expect(screen.getByText(/reachable/i)).toBeInTheDocument();
  });
});

describe('ProxyEditorDrawer credential controls', () => {
  it('shows inline paired-credential errors and blocks create with username only', async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ProxyEditorDrawer open proxy={null} defaultLabel="New proxy" onClose={() => {}} />,
    );

    await user.type(await screen.findByPlaceholderText('proxy.example'), 'proxy.example');
    await user.type(screen.getByPlaceholderText('1080'), '8080');
    const username = document.querySelector<HTMLInputElement>('input[name="username"]');
    expect(username).not.toBeNull();
    await user.type(username!, 'user-only');

    expect(await screen.findByText(/enter both username and password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /create proxy/i })).toBeDisabled();
  });

  it('blocks changing a stored username without a replacement password', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProxyEditorDrawer open proxy={EXISTING} onClose={() => {}} />);

    const username = document.querySelector<HTMLInputElement>('input[name="username"]');
    expect(username).not.toBeNull();
    await user.clear(username!);
    await user.type(username!, 'changed-user');

    expect(await screen.findByText(/enter both username and password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled();
  });

  it('sends an explicit clear request for stored credentials', async () => {
    const update = vi.spyOn(api, 'updateProxy').mockResolvedValue({
      ...EXISTING,
      username: null,
      has_password: false,
    });
    const user = userEvent.setup();
    renderWithProviders(<ProxyEditorDrawer open proxy={EXISTING} onClose={() => {}} />);

    await user.click(await screen.findByRole('switch', { name: /clear stored credentials/i }));
    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(
        EXISTING.id,
        expect.objectContaining({ clear_credentials: true, username: null, password: undefined }),
      ),
    );
  });

  it('cancels a pending clear when a replacement password is typed', async () => {
    const update = vi.spyOn(api, 'updateProxy').mockResolvedValue({
      ...EXISTING,
      username: 'replacement-user',
      has_password: true,
    });
    const user = userEvent.setup();
    renderWithProviders(<ProxyEditorDrawer open proxy={EXISTING} onClose={() => {}} />);

    const clear = await screen.findByRole('switch', { name: /clear stored credentials/i });
    await user.click(clear);
    await user.clear(screen.getByLabelText('Password'));
    await user.type(screen.getByLabelText('Password'), 'replacement-secret');
    expect(clear).toHaveAttribute('aria-checked', 'false');
    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(
        EXISTING.id,
        expect.objectContaining({
          clear_credentials: undefined,
          username: '4v7s',
          password: 'replacement-secret',
        }),
      ),
    );
  });
});

describe('ProxyEditorDrawer authoritative testing', () => {
  // A regression where this fails: changing an existing proxy's host then quick
  // testing still calls the saved-ID endpoint, which tests the old host instead.
  it('quick-tests dirty existing values through the ad-hoc endpoint', async () => {
    const quickAdhoc = vi.spyOn(api, 'quickTestProxyAdhoc').mockResolvedValue({
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
    const staleQuick = vi.spyOn(api, 'quickTestProxy');
    const user = userEvent.setup();
    renderWithProviders(<ProxyEditorDrawer open proxy={EXISTING} onClose={() => {}} />);

    await user.clear(await screen.findByPlaceholderText('proxy.example'));
    await user.type(screen.getByPlaceholderText('proxy.example'), '198.51.100.42');
    await user.type(screen.getByLabelText('Password'), 'replacement-secret');
    await user.click(screen.getByRole('button', { name: /quick test/i }));

    await waitFor(() =>
      expect(quickAdhoc).toHaveBeenCalledWith({
        scheme: 'socks5',
        host: '198.51.100.42',
        port: 17735,
        username: '4v7s',
        password: 'replacement-secret',
      }),
    );
    expect(staleQuick).not.toHaveBeenCalled();
  });

  // A regression where this fails: rendering a stored secret into the field
  // leaks it, while sending an empty string overwrites it during testing.
  it('keeps stored passwords write-only and sends null when no replacement is typed', async () => {
    const quickAdhoc = vi.spyOn(api, 'quickTestProxyAdhoc').mockResolvedValue({
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
    renderWithProviders(<ProxyEditorDrawer open proxy={EXISTING} onClose={() => {}} />);

    expect(await screen.findByLabelText('Password')).toHaveValue('');
    await user.click(screen.getByRole('button', { name: /quick test/i }));
    await waitFor(() =>
      expect(quickAdhoc).toHaveBeenCalledWith(
        expect.objectContaining({
          password: null,
          credential_proxy_id: EXISTING.id,
        }),
      ),
    );
  });

  // A regression where this fails: Full Quality Test runs immediately with the
  // saved ID, so it measures values before the user's edits are persisted.
  it('updates dirty existing values before starting the quality test', async () => {
    const update = vi.spyOn(api, 'updateProxy').mockResolvedValue({
      ...EXISTING,
      host: '198.51.100.42',
    });
    const quality = vi.spyOn(api, 'qualityTestProxy').mockResolvedValue({
      ...QUALITY_RESULT,
      proxy_id: EXISTING.id,
    });
    const user = userEvent.setup();
    renderWithProviders(<ProxyEditorDrawer open proxy={EXISTING} onClose={() => {}} />);

    await user.clear(await screen.findByPlaceholderText('proxy.example'));
    await user.type(screen.getByPlaceholderText('proxy.example'), '198.51.100.42');
    await user.click(screen.getByRole('button', { name: /full quality test/i }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(
        EXISTING.id,
        expect.objectContaining({ host: '198.51.100.42', password: undefined }),
      ),
    );
    await waitFor(() => expect(quality).toHaveBeenCalledWith(EXISTING.id));
  });

  // A regression where this fails: parsing writes form fields with setValue,
  // but react-hook-form does not mark them dirty, so quality tests old saved data.
  it('updates parsed values before starting the quality test', async () => {
    const update = vi.spyOn(api, 'updateProxy').mockResolvedValue({
      ...EXISTING,
      host: '198.51.100.42',
      port: 1080,
      username: 'parsed-user',
    });
    const quality = vi.spyOn(api, 'qualityTestProxy').mockResolvedValue({
      ...QUALITY_RESULT,
      proxy_id: EXISTING.id,
    });
    const user = userEvent.setup();
    renderWithProviders(<ProxyEditorDrawer open proxy={EXISTING} onClose={() => {}} />);

    await user.type(
      await screen.findByPlaceholderText(/socks5h:\/\//i),
      'socks5://parsed-user:parsed-secret@198.51.100.42:1080',
    );
    await user.click(screen.getByRole('button', { name: /full quality test/i }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(
        EXISTING.id,
        expect.objectContaining({
          host: '198.51.100.42',
          port: 1080,
          username: 'parsed-user',
          password: 'parsed-secret',
        }),
      ),
    );
    await waitFor(() => expect(quality).toHaveBeenCalledWith(EXISTING.id));
  });

  // A regression where this fails: toggles write with setValue but do not make
  // the form dirty, so quality testing skips the required persistence update.
  it('updates clear-credentials and launch toggles before quality testing', async () => {
    const update = vi.spyOn(api, 'updateProxy').mockResolvedValue({
      ...EXISTING,
      username: null,
      has_password: false,
      test_before_launch: false,
    });
    const quality = vi.spyOn(api, 'qualityTestProxy').mockResolvedValue({
      ...QUALITY_RESULT,
      proxy_id: EXISTING.id,
    });
    const user = userEvent.setup();
    renderWithProviders(<ProxyEditorDrawer open proxy={EXISTING} onClose={() => {}} />);

    await user.click(await screen.findByRole('switch', { name: /clear stored credentials/i }));
    await user.click(screen.getByRole('switch', { name: /test before launch/i }));
    await user.click(screen.getByRole('button', { name: /full quality test/i }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(
        EXISTING.id,
        expect.objectContaining({
          clear_credentials: true,
          username: null,
          password: undefined,
          test_before_launch: false,
        }),
      ),
    );
    await waitFor(() => expect(quality).toHaveBeenCalledWith(EXISTING.id));
  });

  it('updates a replacement password that cancels clear credentials before quality testing', async () => {
    const update = vi.spyOn(api, 'updateProxy').mockResolvedValue({ ...EXISTING });
    const quality = vi.spyOn(api, 'qualityTestProxy').mockResolvedValue({
      ...QUALITY_RESULT,
      proxy_id: EXISTING.id,
    });
    const user = userEvent.setup();
    renderWithProviders(<ProxyEditorDrawer open proxy={EXISTING} onClose={() => {}} />);

    await user.click(await screen.findByRole('switch', { name: /clear stored credentials/i }));
    await user.type(screen.getByLabelText('Password'), 'replacement-secret');
    await user.click(screen.getByRole('button', { name: /full quality test/i }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(
        EXISTING.id,
        expect.objectContaining({ clear_credentials: undefined, password: 'replacement-secret' }),
      ),
    );
    await waitFor(() => expect(quality).toHaveBeenCalledWith(EXISTING.id));
  });

  // A regression where this fails: after saving the dirty form, a quality-test
  // error resets the write-only password input and loses the replacement secret.
  it('keeps typed values and the error visible when quality testing fails', async () => {
    vi.spyOn(api, 'updateProxy').mockResolvedValue({
      ...EXISTING,
      host: '198.51.100.42',
    });
    vi.spyOn(api, 'qualityTestProxy').mockRejectedValue(new Error('Quality service unavailable'));
    const user = userEvent.setup();
    renderWithProviders(<ProxyEditorDrawer open proxy={EXISTING} onClose={() => {}} />);

    await user.clear(await screen.findByPlaceholderText('proxy.example'));
    await user.type(screen.getByPlaceholderText('proxy.example'), '198.51.100.42');
    await user.type(screen.getByLabelText('Password'), 'replacement-secret');
    await user.click(screen.getByRole('button', { name: /full quality test/i }));

    expect(await screen.findByText('Quality service unavailable')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('proxy.example')).toHaveValue('198.51.100.42');
    expect(screen.getByLabelText('Password')).toHaveValue('replacement-secret');
  });

  // A regression where this fails: Full Quality Test has no ID for a new proxy
  // and either errors or tries the job before the create mutation completes.
  it('creates a new proxy before starting the quality test', async () => {
    const created = { ...EXISTING, id: 'px-created', has_password: false };
    const create = vi.spyOn(api, 'createProxy').mockResolvedValue(created);
    const quality = vi.spyOn(api, 'qualityTestProxy').mockResolvedValue({
      ...QUALITY_RESULT,
      proxy_id: created.id,
    });
    const user = userEvent.setup();
    renderWithProviders(
      <ProxyEditorDrawer open proxy={null} defaultLabel="New proxy" onClose={() => {}} />,
    );

    await user.type(
      await screen.findByPlaceholderText(/socks5h:\/\//i),
      'socks5://new-user:new-secret@198.51.100.42:1080',
    );
    await user.click(screen.getByRole('button', { name: /full quality test/i }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({
          label: 'New proxy',
          host: '198.51.100.42',
          port: 1080,
          username: 'new-user',
          password: 'new-secret',
        }),
      ),
    );
    await waitFor(() => expect(quality).toHaveBeenCalledWith(created.id));
  });

  // A regression where this fails: onSaved changes the parent prop from null to
  // the newly created proxy, and the ID reset erases the quality failure state.
  it('keeps typed values and a quality error through the parent create refetch', async () => {
    const created = { ...EXISTING, id: 'px-created', has_password: false };
    vi.spyOn(api, 'createProxy').mockResolvedValue(created);
    vi.spyOn(api, 'qualityTestProxy').mockRejectedValue(new Error('Quality service unavailable'));
    const user = userEvent.setup();
    renderWithProviders(<CreateRefetchHarness />);

    await user.type(
      await screen.findByPlaceholderText(/socks5h:\/\//i),
      'socks5://new-user:new-secret@198.51.100.42:1080',
    );
    await user.click(screen.getByRole('button', { name: /full quality test/i }));

    expect(await screen.findByText('Quality service unavailable')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('proxy.example')).toHaveValue('198.51.100.42');
    expect(screen.getByLabelText('Password')).toHaveValue('new-secret');
  });
});
