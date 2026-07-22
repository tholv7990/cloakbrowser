import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import { mockStore } from '@/mocks/store';
import { mockApi } from '@/mocks/mockApi';
import { DiagnosticsPage } from './DiagnosticsPage';

describe('DiagnosticsPage', () => {
  beforeEach(() => mockStore.reset());

  it('renders all supported target selectors and observation history', async () => {
    renderWithProviders(<DiagnosticsPage />);
    expect(
      await screen.findByRole('button', { name: /direct google control/i }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole('option', { name: /pixelscan/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('option', { name: /iphey/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('option', { name: /cloudflare/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('option', { name: /google search/i }).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/observed/i)).length).toBeGreaterThan(0);
  });

  it('uses explicit user-action wording for CAPTCHA observations', async () => {
    mockStore.diagnostics.unshift({
      id: 'diag-captcha',
      profile_id: 'prof-01',
      kind: 'google_search',
      status: 'warning',
      target_url: 'https://www.google.com/search?q=CloakBrowser+browser+diagnostic',
      requested_at: '2026-07-22T00:00:00Z',
      started_at: '2026-07-22T00:00:01Z',
      completed_at: '2026-07-22T00:00:02Z',
      progress: 100,
      summary: 'Diagnostic completed with warnings.',
      findings: { captcha_detected: true },
      screenshot_path: null,
      report_path: null,
      error_code: 'captcha_user_action_required',
      error_message: 'The target requires user interaction.',
    });
    renderWithProviders(<DiagnosticsPage />);
    expect(
      await screen.findByText(/captcha detected.*user action is required/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/solve captcha/i)).not.toBeInTheDocument();
  });

  it('renders bounded labeled findings and an accessible progress bar', async () => {
    mockStore.diagnostics.unshift({
      ...mockStore.diagnostics[0],
      id: 'finding-run',
      status: 'running',
      progress: 42,
      findings: { page_loaded: true, captcha_detected: false },
    });
    renderWithProviders(<DiagnosticsPage />);

    expect((await screen.findAllByText('Page loaded')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Yes').length).toBeGreaterThan(0);
    expect(
      screen
        .getAllByRole('progressbar')
        .find((element) => element.getAttribute('aria-valuenow') === '42'),
    ).toBeDefined();
  });

  it('sends profile and pagination controls to diagnostic history', async () => {
    const user = userEvent.setup();
    const list = vi.spyOn(mockApi, 'listDiagnostics');
    mockStore.diagnostics = Array.from({ length: 21 }, (_, index) => ({
      ...mockStore.diagnostics[0],
      id: `diagnostic-${index}`,
      profile_id: mockStore.profiles[0].id,
    }));
    renderWithProviders(<DiagnosticsPage />);

    await screen.findAllByText(/observed/i);
    await user.selectOptions(
      screen.getByLabelText(/filter history by profile/i),
      mockStore.profiles[0].id,
    );
    await waitFor(() =>
      expect(list).toHaveBeenLastCalledWith(
        expect.objectContaining({ profile: mockStore.profiles[0].id }),
      ),
    );
    await user.click(await screen.findByRole('button', { name: /next diagnostic page/i }));
    await waitFor(() =>
      expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, page_size: 20 })),
    );
  });
});
