import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import { BulkActionsBar } from './BulkActionsBar';

function setup(overrides = {}) {
  const props = {
    count: 3,
    folders: [],
    statuses: [],
    tags: [],
    onAction: vi.fn(),
    onLaunch: vi.fn(),
    onStop: vi.fn(),
    onAssignProxies: vi.fn(),
    onClear: vi.fn(),
    ...overrides,
  };
  renderWithProviders(<BulkActionsBar {...props} />);
  return props;
}

describe('BulkActionsBar', () => {
  it('launches and stops the selection', async () => {
    const user = userEvent.setup();
    const props = setup();
    await user.click(screen.getByRole('button', { name: /^launch$/i }));
    await user.click(screen.getByRole('button', { name: /^stop$/i }));
    expect(props.onLaunch).toHaveBeenCalledTimes(1);
    expect(props.onStop).toHaveBeenCalledTimes(1);
  });

  it('renders nothing with no selection', () => {
    setup({ count: 0 });
    expect(screen.queryByRole('button', { name: /^launch$/i })).not.toBeInTheDocument();
  });
});
