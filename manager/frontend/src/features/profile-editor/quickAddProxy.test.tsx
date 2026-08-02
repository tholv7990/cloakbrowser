import { useState } from 'react';
import { FormProvider, useForm, useWatch } from 'react-hook-form';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import { api } from '@/api';
import { mockStore } from '@/mocks/store';
import type { Proxy } from '@/types/api';
import { useProxies } from '@/features/proxies/api';
import { ProxyEditorDrawer } from '@/features/proxies/ProxyEditorDrawer';
import { defaultWizardValues, type ProfileWizardValues } from '@/schemas/profile';
import { WIZARD_STEPS, type WizardRefs } from './steps';

const ProxyLocationStep = WIZARD_STEPS[1].Component;

function SelectedProxy() {
  const proxyId = useWatch<ProfileWizardValues>({ name: 'proxy_id' }) as string;
  return <div data-testid="proxy-id">{proxyId}</div>;
}

function Harness() {
  const form = useForm<ProfileWizardValues>({
    defaultValues: defaultWizardValues({ name: 'Drawer profile' }),
  });
  const proxies = useProxies();
  const proxyId = useWatch({ control: form.control, name: 'proxy_id' });
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [lastSavedProxy, setLastSavedProxy] = useState<Proxy | null>(null);
  const selectedProxy =
    (lastSavedProxy?.id === proxyId ? lastSavedProxy : null) ??
    (proxies.data ?? []).find((proxy) => proxy.id === proxyId) ??
    null;
  const removeAssignment = () => {
    form.setValue('proxy_id', '', { shouldDirty: true, shouldValidate: true });
    setLastSavedProxy(null);
  };
  const refs: WizardRefs = {
    folders: [],
    statuses: [],
    tags: [],
    proxies: proxies.data ?? [],
    extensions: [],
    browserVersion: '146',
    platform: 'windows',
    isEdit: false,
    selectedProxy,
    onOpenProxyEditor: () => setDrawerOpen(true),
    onRemoveProxyAssignment: removeAssignment,
  };
  return (
    <FormProvider {...form}>
      <ProxyLocationStep refs={refs} />
      <SelectedProxy />
      <ProxyEditorDrawer
        open={drawerOpen}
        proxy={selectedProxy}
        defaultLabel="Drawer profile"
        onClose={() => setDrawerOpen(false)}
        onSaved={(proxy) => {
          setLastSavedProxy(proxy);
          form.setValue('proxy_id', proxy.id, { shouldDirty: true, shouldValidate: true });
        }}
        onRemove={selectedProxy ? removeAssignment : undefined}
      />
    </FormProvider>
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  mockStore.reset();
});

describe('proxy drawer from the profile form', () => {
  it('creates and assigns a proxy through the shared drawer', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);
    expect(screen.getByTestId('proxy-id')).toHaveTextContent('');

    await user.click(screen.getByRole('button', { name: /^add$/i }));
    await user.type(
      await screen.findByPlaceholderText(/socks5h:\/\//i),
      'socks5://bob:secret@203.0.113.9:1080',
    );
    await user.click(screen.getByRole('button', { name: /create proxy/i }));

    await waitFor(() => expect(screen.getByTestId('proxy-id')).not.toHaveTextContent(''));
    await user.click(
      within(screen.getByRole('dialog', { name: /edit proxy/i })).getAllByRole('button', {
        name: /close/i,
      })[0],
    );
    expect(screen.getByText('socks5://***:***@203.0.113.9:1080')).toBeInTheDocument();
  });

  it('clears the assignment without deleting the reusable proxy', async () => {
    const deleteProxy = vi.spyOn(api, 'deleteProxy');
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole('button', { name: /^add$/i }));
    await user.type(
      await screen.findByPlaceholderText(/socks5h:\/\//i),
      'http://bob:secret@203.0.113.9:8080',
    );
    await user.click(screen.getByRole('button', { name: /create proxy/i }));
    await user.click(
      within(await screen.findByRole('dialog', { name: /edit proxy/i })).getAllByRole('button', {
        name: /close/i,
      })[0],
    );
    await waitFor(() => expect(screen.getByRole('button', { name: /^remove$/i })).toBeEnabled());
    const savedProxy = mockStore.proxies[mockStore.proxies.length - 1];

    await user.click(screen.getByRole('button', { name: /^remove$/i }));

    expect(screen.getByTestId('proxy-id')).toHaveTextContent('');
    expect(mockStore.proxies.some((proxy) => proxy.id === savedProxy.id)).toBe(true);
    expect(deleteProxy).not.toHaveBeenCalled();
  });
});
