import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { mockStore } from '@/mocks/store';
import { renderWithProviders } from '@/test/utils';
import { ResourcesPage } from './ResourcesPage';

describe('ResourcesPage', () => {
  beforeEach(() => mockStore.reset());

  it('owns vertical scrolling inside the overflow-hidden app shell', () => {
    const { container } = renderWithProviders(<ResourcesPage />);
    expect(container.firstElementChild).toHaveClass('h-full', 'overflow-y-auto');
  });

  it('mounts the resource monitor and session history against the mock backend', async () => {
    renderWithProviders(<ResourcesPage />);

    expect(await screen.findByText('Resource monitor')).toBeInTheDocument();
    expect(screen.getByText('Recent sessions')).toBeInTheDocument();
  });
});
