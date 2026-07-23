import { FormProvider, useForm, useWatch } from 'react-hook-form';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import { mockApi } from '@/mocks/mockApi';
import { mockStore } from '@/mocks/store';
import { useProxies } from '@/features/proxies/api';
import { defaultWizardValues, type ProfileWizardValues } from '@/schemas/profile';
import { WIZARD_STEPS, type WizardRefs } from './steps';

const ProxyLocationStep = WIZARD_STEPS[1].Component;

function SelectedProxy() {
  const proxyId = useWatch<ProfileWizardValues>({ name: 'proxy_id' }) as string;
  return <div data-testid="proxy-id">{proxyId}</div>;
}

function Harness() {
  const form = useForm<ProfileWizardValues>({ defaultValues: defaultWizardValues() });
  const proxies = useProxies();
  const refs: WizardRefs = {
    folders: [],
    statuses: [],
    tags: [],
    proxies: proxies.data ?? [], // live, so a created proxy becomes selectable
    extensions: [],
    browserVersion: '146',
    platform: 'windows',
    isEdit: false,
  };
  return (
    <FormProvider {...form}>
      <ProxyLocationStep refs={refs} />
      <SelectedProxy />
    </FormProvider>
  );
}

beforeEach(() => mockStore.reset());

describe('quick-add proxy from the profile form', () => {
  it('creates and selects a proxy from a single pasted string', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);
    expect(screen.getByTestId('proxy-id')).toHaveTextContent('');

    await user.type(screen.getByPlaceholderText(/host:port:user:pass/i), '203.0.113.9:1080:bob:secret');
    await user.click(screen.getByRole('button', { name: /add & use/i }));

    await waitFor(() => expect(screen.getByTestId('proxy-id')).not.toHaveTextContent(''));
  });

  it('checks the added proxy inline and shows the geo result', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);
    await user.type(screen.getByPlaceholderText(/host:port:user:pass/i), '203.0.113.9:1080:bob:secret');
    await user.click(screen.getByRole('button', { name: /add & use/i }));

    // Once created + selected + refetched, the inline "Check proxy" button appears.
    const check = await screen.findByRole('button', { name: /check proxy/i });
    await user.click(check);
    // The geo result renders inline (reachable badge from the mock quick test).
    await waitFor(() => expect(screen.getByText(/reachable/i)).toBeInTheDocument());
  });

  it('surfaces a check failure instead of failing silently', async () => {
    vi.spyOn(mockApi, 'quickTestProxy').mockRejectedValueOnce(new Error('Proxy unreachable'));
    const user = userEvent.setup();
    renderWithProviders(<Harness />);
    await user.type(screen.getByPlaceholderText(/host:port:user:pass/i), '203.0.113.9:1080:bob:secret');
    // Adding auto-runs the check; a failed check must show, not vanish.
    await user.click(screen.getByRole('button', { name: /add & use/i }));
    expect(await screen.findByText(/proxy unreachable/i)).toBeInTheDocument();
  });

  it('shows an error for an unparseable proxy without creating one', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);
    await user.type(screen.getByPlaceholderText(/host:port:user:pass/i), 'not-a-proxy');
    await user.click(screen.getByRole('button', { name: /add & use/i }));

    expect(await screen.findByText(/could not read that proxy/i)).toBeInTheDocument();
    expect(screen.getByTestId('proxy-id')).toHaveTextContent('');
  });
});
