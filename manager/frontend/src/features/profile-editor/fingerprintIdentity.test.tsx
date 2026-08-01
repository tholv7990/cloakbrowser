import { FormProvider, useForm } from 'react-hook-form';
import { describe, expect, it } from 'vitest';
import userEvent from '@testing-library/user-event';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';
import { defaultWizardValues, type ProfileWizardValues } from '@/schemas/profile';
import type { FingerprintCoherenceResult } from '@/features/profiles/types';
import { WIZARD_STEPS, type WizardRefs } from './steps';

const refs: WizardRefs = {
  folders: [],
  statuses: [],
  tags: [],
  proxies: [],
  extensions: [],
  browserVersion: '146.0.7680.177',
  platform: 'windows',
  isEdit: false,
};

function StepHarness({
  step,
  values = defaultWizardValues(),
  coherence = null,
}: {
  step: number;
  values?: ProfileWizardValues;
  coherence?: FingerprintCoherenceResult | null;
}) {
  const form = useForm<ProfileWizardValues>({ defaultValues: values });
  const Step = WIZARD_STEPS[step].Component;
  return (
    <FormProvider {...form}>
      <Step refs={{ ...refs, coherence }} />
    </FormProvider>
  );
}

describe('explicit fingerprint attributes editor', () => {
  it('starts collapsed and exposes optional identity controls on request', async () => {
    const user = userEvent.setup();
    renderWithProviders(<StepHarness step={2} />);

    expect(screen.getByLabelText('GPU vendor')).not.toBeVisible();
    await user.click(screen.getByText('Explicit fingerprint attributes'));

    expect(screen.getByLabelText('GPU vendor')).toHaveValue('');
    expect(screen.getByLabelText('GPU renderer')).toHaveValue('');
    expect(screen.getByLabelText('Screen width')).toHaveValue(null);
    expect(screen.getByLabelText('Screen height')).toHaveValue(null);
  });

  it('renders a localized backend finding beside its field', async () => {
    const user = userEvent.setup();
    const coherence: FingerprintCoherenceResult = {
      status: 'error',
      findings: [
        {
          code: 'gpu.platform_mismatch',
          severity: 'error',
          field: 'gpu_renderer',
          message: 'Server text is not rendered.',
        },
      ],
    };
    renderWithProviders(<StepHarness step={2} coherence={coherence} />);

    await user.click(screen.getByText('Explicit fingerprint attributes'));

    const renderer = screen.getByLabelText('GPU renderer');
    expect(renderer).toHaveAccessibleDescription(
      'GPU renderer is incompatible with the Windows browser persona.',
    );
    expect(screen.queryByText('Server text is not rendered.')).not.toBeInTheDocument();
  });

  it('keeps every backend finding adjacent when a field has multiple findings', async () => {
    const user = userEvent.setup();
    const coherence: FingerprintCoherenceResult = {
      status: 'error',
      findings: [
        {
          code: 'gpu.vendor_renderer_mismatch',
          severity: 'error',
          field: 'gpu_renderer',
          message: 'Server text is not rendered.',
        },
        {
          code: 'gpu.platform_mismatch',
          severity: 'error',
          field: 'gpu_renderer',
          message: 'Server text is not rendered.',
        },
      ],
    };
    renderWithProviders(<StepHarness step={2} coherence={coherence} />);

    await user.click(screen.getByText('Explicit fingerprint attributes'));

    expect(screen.getByLabelText('GPU renderer')).toHaveAccessibleDescription(
      'GPU vendor and renderer identify different hardware families. GPU renderer is incompatible with the Windows browser persona.',
    );
  });

  it('shows only explicit overrides in the review section', () => {
    renderWithProviders(
      <StepHarness
        step={7}
        values={defaultWizardValues({
          gpu_vendor: 'Neutral Graphics',
          hardware_concurrency: '12',
          brand: 'BrowserCo',
        })}
      />,
    );

    expect(screen.getByText('Explicit fingerprint attributes')).toBeInTheDocument();
    expect(screen.getByText('Neutral Graphics')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('BrowserCo')).toBeInTheDocument();
    expect(screen.queryByText('GPU renderer')).not.toBeInTheDocument();
    expect(screen.queryByText('Screen size')).not.toBeInTheDocument();
  });
});
