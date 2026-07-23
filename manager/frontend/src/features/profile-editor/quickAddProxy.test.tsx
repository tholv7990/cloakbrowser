import { FormProvider, useForm, useWatch } from 'react-hook-form';
import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import { mockStore } from '@/mocks/store';
import { defaultWizardValues, type ProfileWizardValues } from '@/schemas/profile';
import { WIZARD_STEPS, type WizardRefs } from './steps';

const ProxyLocationStep = WIZARD_STEPS[1].Component;

const refs: WizardRefs = {
  folders: [],
  statuses: [],
  tags: [],
  proxies: [],
  extensions: [],
  browserVersion: '146',
  isEdit: false,
};

function SelectedProxy() {
  const proxyId = useWatch<ProfileWizardValues>({ name: 'proxy_id' }) as string;
  return <div data-testid="proxy-id">{proxyId}</div>;
}

function Harness() {
  const form = useForm<ProfileWizardValues>({ defaultValues: defaultWizardValues() });
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

  it('shows an error for an unparseable proxy without creating one', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);
    await user.type(screen.getByPlaceholderText(/host:port:user:pass/i), 'not-a-proxy');
    await user.click(screen.getByRole('button', { name: /add & use/i }));

    expect(await screen.findByText(/could not read that proxy/i)).toBeInTheDocument();
    expect(screen.getByTestId('proxy-id')).toHaveTextContent('');
  });
});
