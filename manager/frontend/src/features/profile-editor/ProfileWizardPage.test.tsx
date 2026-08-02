import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { renderWithProviders } from '@/test/utils';
import { api } from '@/api';
import { mockStore } from '@/mocks/store';
import type { ProfileRead, Proxy } from '@/types/api';
import * as profilesApi from '@/features/profiles/api';
import { ProfileWizardPage } from './ProfileWizardPage';

const mutationMocks = vi.hoisted(() => ({
  create: vi.fn(),
  update: vi.fn(),
}));

const queryMocks = vi.hoisted(() => ({
  proxies: [] as Proxy[],
  profile: null as ProfileRead | null,
  profileExtensions: { extension_ids: [] as string[] },
}));

vi.mock('@/hooks/useAppData', () => ({
  useAppData: () => ({
    folders: [],
    tags: [],
    statuses: [],
    extensions: [],
    browser: {
      name: 'Plasma Chromium',
      version: '146.0.7680.177',
      chromium_version: '146.0.7680.177',
      path_present: true,
    },
    browserVersion: '146.0.7680.177',
    platform: 'windows',
    runningCount: 0,
    profileRoot: '',
    isLoading: false,
    isError: false,
  }),
}));

vi.mock('@/features/proxies/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/features/proxies/api')>()),
  useProxies: () => ({ data: queryMocks.proxies, isLoading: false, isError: false }),
}));

vi.mock('./api', () => ({
  useCreateProfile: () => ({ isPending: false, mutateAsync: mutationMocks.create }),
  useUpdateProfile: () => ({ isPending: false, mutateAsync: mutationMocks.update }),
  useProfile: () => ({ data: queryMocks.profile ?? undefined, isLoading: false, isError: false }),
  useProfileExtensions: () => ({
    data: queryMocks.profile ? queryMocks.profileExtensions : undefined,
    isLoading: false,
    isError: false,
  }),
}));

beforeEach(() => {
  vi.restoreAllMocks();
  mutationMocks.create.mockReset();
  mutationMocks.update.mockReset();
  mockStore.reset();
  queryMocks.proxies = [];
  queryMocks.profile = null;
  vi.spyOn(profilesApi, 'validateProfileDraft').mockResolvedValue({
    status: 'coherent',
    findings: [],
  });
  class IntersectionObserverStub {
    observe() {}
    disconnect() {}
  }
  vi.stubGlobal('IntersectionObserver', IntersectionObserverStub);
});

describe('ProfileWizardPage proxy drawer', () => {
  it('selects an existing proxy for an unassigned profile without creating one', async () => {
    const existing = mockStore.proxies[0];
    queryMocks.proxies = [existing];
    mutationMocks.create.mockResolvedValue({
      ...mockStore.profiles[0],
      id: 'new-profile-with-existing-proxy',
      name: 'Advanced existing',
      proxy_id: existing.id,
    });
    const createProxy = vi.spyOn(api, 'createProxy');
    const user = userEvent.setup();
    renderWithProviders(<ProfileWizardPage mode="create" />);

    await user.type(screen.getByPlaceholderText('e.g. marketplace-us-01'), 'Advanced existing');
    await user.click(screen.getByRole('button', { name: /^add$/i }));
    const catalog = await waitFor(() => {
      const select = screen
        .getAllByRole('combobox')
        .find((item) => within(item).queryByRole('option', { name: existing.label }));
      if (!select) throw new Error('existing proxy catalog not found');
      return select;
    });
    await user.selectOptions(catalog, existing.id);
    await user.click(screen.getByRole('button', { name: /use existing proxy/i }));
    await user.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(mutationMocks.create).toHaveBeenCalled());
    expect(mutationMocks.create.mock.calls.at(-1)?.[0]).toEqual(
      expect.objectContaining({ proxy_id: existing.id }),
    );
    expect(createProxy).not.toHaveBeenCalled();
  });

  it('edits the assigned reusable proxy without replacing its ID', async () => {
    const user = userEvent.setup();
    const selectedProxy = mockStore.proxies[0];
    const profile = { ...mockStore.profiles[0], proxy_id: selectedProxy.id };
    queryMocks.proxies = [selectedProxy];
    queryMocks.profile = profile;
    mutationMocks.update.mockResolvedValue(profile);
    const updateProxy = vi.spyOn(api, 'updateProxy');

    renderWithProviders(
      <Routes>
        <Route path="/profiles/:id" element={<ProfileWizardPage mode="edit" />} />
        <Route path="/profiles" element={<div>Profiles</div>} />
      </Routes>,
      { route: `/profiles/${profile.id}` },
    );

    await user.click(await screen.findByRole('button', { name: /^edit$/i }));
    await user.clear(await screen.findByPlaceholderText('proxy.example'));
    await user.type(screen.getByPlaceholderText('proxy.example'), '198.51.100.77');
    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() =>
      expect(updateProxy).toHaveBeenCalledWith(
        selectedProxy.id,
        expect.objectContaining({ host: '198.51.100.77' }),
      ),
    );
    await user.click(
      within(screen.getByRole('dialog', { name: /edit proxy/i })).getAllByRole('button', {
        name: /close/i,
      })[0],
    );
    await user.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(mutationMocks.update).toHaveBeenCalled());
    expect(mutationMocks.update.mock.calls.at(-1)?.[0].payload).not.toHaveProperty('proxy_id');
  });
});

describe('ProfileWizardPage fingerprint coherence validation', () => {
  it('debounces a backend validation request for the current draft', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProfileWizardPage mode="create" />);

    await user.click(screen.getByRole('button', { name: 'Advanced settings' }));
    await user.click(screen.getByText('Explicit fingerprint attributes'));
    await user.type(screen.getByLabelText('GPU vendor'), 'Neutral Graphics');

    await waitFor(
      () =>
        expect(profilesApi.validateProfileDraft).toHaveBeenLastCalledWith(
          expect.objectContaining({
            gpu_vendor: 'Neutral Graphics',
            gpu_renderer: null,
            screen_width: null,
            screen_height: null,
          }),
        ),
      { timeout: 1500 },
    );
  });

  it('announces a warning without disabling save actions', async () => {
    vi.mocked(profilesApi.validateProfileDraft).mockResolvedValue({
      status: 'warning',
      findings: [
        {
          code: 'geo.timezone_mismatch',
          severity: 'warning',
          field: 'location.timezone',
          message: 'Server text is not rendered.',
        },
      ],
    });
    renderWithProviders(<ProfileWizardPage mode="create" />);

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Manual timezone differs from the verified proxy timezone.',
    );
    expect(screen.getByRole('button', { name: /^save$/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /save .* run/i })).toBeEnabled();
  });

  it('announces an error and disables both save actions', async () => {
    vi.mocked(profilesApi.validateProfileDraft).mockResolvedValue({
      status: 'error',
      findings: [
        {
          code: 'ua.platform_mismatch',
          severity: 'error',
          field: 'custom_user_agent',
          message: 'Server text is not rendered.',
        },
      ],
    });
    renderWithProviders(<ProfileWizardPage mode="create" />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Custom user agent must identify Windows.',
    );
    expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /save .* run/i })).toBeDisabled();
  });

  it('does not let a delayed pre-save response overwrite validation for a newer draft', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProfileWizardPage mode="create" />);
    await waitFor(() => expect(profilesApi.validateProfileDraft).toHaveBeenCalled());
    await user.type(screen.getByPlaceholderText('e.g. marketplace-us-01'), 'Guarded');
    await waitFor(() => expect(profilesApi.validateProfileDraft).toHaveBeenCalledTimes(2), {
      timeout: 1500,
    });

    let resolveOld!: (value: Awaited<ReturnType<typeof profilesApi.validateProfileDraft>>) => void;
    const oldResponse = new Promise<Awaited<ReturnType<typeof profilesApi.validateProfileDraft>>>(
      (resolve) => {
        resolveOld = resolve;
      },
    );
    vi.mocked(profilesApi.validateProfileDraft).mockReset();
    vi.mocked(profilesApi.validateProfileDraft).mockImplementation((draft) =>
      draft.gpu_vendor
        ? Promise.resolve({
            status: 'warning',
            findings: [
              {
                code: 'geo.timezone_mismatch',
                severity: 'warning',
                field: 'location.timezone',
                message: 'Server text is not rendered.',
              },
            ],
          })
        : oldResponse,
    );

    await user.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(profilesApi.validateProfileDraft).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', { name: 'Advanced settings' }));
    await user.click(screen.getByText('Explicit fingerprint attributes'));
    await user.type(screen.getByLabelText('GPU vendor'), 'Neutral Graphics');

    expect(await screen.findByRole('status', {}, { timeout: 1500 })).toHaveTextContent(
      'Manual timezone differs from the verified proxy timezone.',
    );
    resolveOld({
      status: 'error',
      findings: [
        {
          code: 'gpu.platform_mismatch',
          severity: 'error',
          field: 'gpu_renderer',
          message: 'Server text is not rendered.',
        },
      ],
    });
    await act(async () => oldResponse);

    expect(screen.getByRole('status')).toHaveTextContent(
      'Manual timezone differs from the verified proxy timezone.',
    );
    expect(screen.queryByText('GPU renderer is incompatible')).not.toBeInTheDocument();
    expect(mutationMocks.create).not.toHaveBeenCalled();
  });

  it('blocks persistence and announces a localized validation request failure', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProfileWizardPage mode="create" />);
    await waitFor(() => expect(profilesApi.validateProfileDraft).toHaveBeenCalled());
    await user.type(screen.getByPlaceholderText('e.g. marketplace-us-01'), 'Offline guard');
    await waitFor(() => expect(profilesApi.validateProfileDraft).toHaveBeenCalledTimes(2), {
      timeout: 1500,
    });
    vi.mocked(profilesApi.validateProfileDraft).mockRejectedValueOnce(new Error('offline'));

    await user.click(screen.getByRole('button', { name: /^save$/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Fingerprint validation is unavailable. Try saving again.',
    );
    expect(mutationMocks.create).not.toHaveBeenCalled();
  });

  it('admits only one save transaction while validation is pending', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProfileWizardPage mode="create" />);
    await waitFor(() => expect(profilesApi.validateProfileDraft).toHaveBeenCalled());
    await user.type(screen.getByPlaceholderText('e.g. marketplace-us-01'), 'Single submit');
    await waitFor(() => expect(profilesApi.validateProfileDraft).toHaveBeenCalledTimes(2), {
      timeout: 1500,
    });
    vi.mocked(profilesApi.validateProfileDraft).mockReset();
    vi.mocked(profilesApi.validateProfileDraft).mockImplementation(() => new Promise(() => {}));
    const save = screen.getByRole('button', { name: /^save$/i });

    act(() => {
      fireEvent.click(save);
      fireEvent.click(save);
    });

    await waitFor(() => expect(profilesApi.validateProfileDraft).toHaveBeenCalledTimes(1));
    expect(save).toBeDisabled();
  });
});
