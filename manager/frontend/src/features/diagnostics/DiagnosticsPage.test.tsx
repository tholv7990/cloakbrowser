import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import { mockStore } from '@/mocks/store';
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
});
