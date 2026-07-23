import { useState } from 'react';
import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import { mockStore } from '@/mocks/store';
import { ProxyEditorDrawer } from './ProxyEditorDrawer';

beforeEach(() => mockStore.reset());

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
