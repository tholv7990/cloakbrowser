import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const capabilities = {
  authentication: true,
  profiles: true,
  catalogs: true,
  proxy_management: true,
  browser_runtime: true,
  fingerprint_diagnostics: true,
  settings: true,
  automation: true,
  shopify_builder: true,
  media: true,
  resources: true,
};

async function renderSidebar(appVersion?: string, collapsed = false) {
  vi.resetModules();
  vi.doMock('@/hooks/useAppData', () => ({ useCapabilities: () => capabilities }));
  Object.defineProperty(window, '__CLOAKBROWSER__', {
    configurable: true,
    value: appVersion ? ({ appVersion } as unknown) : undefined,
  });

  const { Sidebar } = await import('./Sidebar');
  const { useUiStore } = await import('@/app/uiStore');
  useUiStore.setState({ sidebarCollapsed: collapsed });

  render(
    <MemoryRouter>
      <Sidebar />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.doUnmock('@/hooks/useAppData');
  Object.defineProperty(window, '__CLOAKBROWSER__', { configurable: true, value: undefined });
});

describe('Sidebar desktop version', () => {
  it('shows the injected desktop version beside the collapse control when expanded', async () => {
    await renderSidebar('1.0.1');

    expect(screen.getByText('Plasma v1.0.1')).toBeInTheDocument();
  });

  it('offers the injected desktop version as a title when collapsed', async () => {
    await renderSidebar('1.0.1', true);

    expect(screen.getByRole('img', { name: 'Plasma v1.0.1' })).toHaveAttribute(
      'title',
      'Plasma v1.0.1',
    );
  });

  it('does not show a desktop version when no version is injected', async () => {
    await renderSidebar();

    expect(screen.queryByText(/Plasma v\d/)).not.toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /Plasma v\d/ })).not.toBeInTheDocument();
  });
});
