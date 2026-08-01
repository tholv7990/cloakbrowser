import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import * as profilesApi from '@/features/profiles/api';
import { ProfileWizardPage } from './ProfileWizardPage';

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
  useProxies: () => ({ data: [], isLoading: false, isError: false }),
  useCreateProxy: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useQuickTest: () => ({ isPending: false, mutateAsync: vi.fn() }),
}));

vi.mock('./api', () => ({
  useCreateProfile: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useUpdateProfile: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useProfile: () => ({ data: undefined, isLoading: false, isError: false }),
  useProfileExtensions: () => ({ data: undefined, isLoading: false, isError: false }),
}));

beforeEach(() => {
  vi.restoreAllMocks();
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
});
