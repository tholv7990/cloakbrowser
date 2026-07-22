import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { FormProvider, useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { AlertTriangle, ArrowLeft, ArrowRight, Check, Play, Save, X } from 'lucide-react';
import { api } from '@/api';
import { useAppData } from '@/hooks/useAppData';
import { useProxies } from '@/features/proxies/api';
import { Button } from '@/components/ui/Button';
import { IconButton } from '@/components/ui/IconButton';
import { LoadingBlock, ErrorState } from '@/components/ui/states';
import { cn } from '@/lib/cn';
import {
  defaultWizardValues,
  profileToWizardValues,
  profileWizardSchema,
  stepFields,
  wizardValuesToPatch,
  wizardValuesToPayload,
  type ProfileWizardValues,
} from '@/schemas/profile';
import { WIZARD_STEPS, type WizardRefs } from './steps';
import { useCreateProfile, useProfile, useUpdateProfile } from './api';
import { persistProfileWithExtensions } from './persistence';
import { useT } from '@/i18n';
import type { ProfileRead } from '@/types/api';

export function ProfileWizardPage({ mode }: { mode: 'create' | 'edit' }) {
  const t = useT();
  const params = useParams();
  const navigate = useNavigate();
  const editingId = mode === 'edit' ? (params.id ?? null) : null;

  const app = useAppData();
  const proxiesQuery = useProxies();
  const profileQuery = useProfile(editingId);
  const createProfile = useCreateProfile();
  const updateProfile = useUpdateProfile();

  const [step, setStep] = useState(0);
  const [savedProfile, setSavedProfile] = useState<ProfileRead | null>(null);
  const [assignmentPending, setAssignmentPending] = useState(false);
  const [persisting, setPersisting] = useState(false);

  const form = useForm<ProfileWizardValues>({
    resolver: zodResolver(profileWizardSchema),
    defaultValues: defaultWizardValues(),
    mode: 'onBlur',
  });

  // Load an existing profile into the form once (edit mode).
  useEffect(() => {
    if (mode === 'edit' && profileQuery.data) {
      form.reset(profileToWizardValues(profileQuery.data));
    }
  }, [mode, profileQuery.data, form]);

  const refs: WizardRefs = useMemo(
    () => ({
      folders: app.folders,
      statuses: app.statuses,
      tags: app.tags,
      proxies: proxiesQuery.data ?? [],
      extensions: app.extensions,
      browserVersion: app.browserVersion,
      isEdit: mode === 'edit',
    }),
    [
      app.folders,
      app.statuses,
      app.tags,
      app.extensions,
      app.browserVersion,
      proxiesQuery.data,
      mode,
    ],
  );

  if (app.isLoading || (mode === 'edit' && profileQuery.isLoading)) {
    return <LoadingBlock label={t('editor.loading')} />;
  }
  if (app.isError) {
    return <ErrorState message={t('editor.loadError')} onRetry={() => window.location.reload()} />;
  }
  if (mode === 'edit' && profileQuery.isError) {
    return (
      <ErrorState message={t('editor.loadProfileError')} onRetry={() => profileQuery.refetch()} />
    );
  }

  const isLast = step === WIZARD_STEPS.length - 1;
  const saving = createProfile.isPending || updateProfile.isPending || persisting;

  const goNext = async () => {
    const valid = await form.trigger(stepFields[step]);
    if (valid) setStep((current) => Math.min(current + 1, WIZARD_STEPS.length - 1));
  };

  const persist = async (): Promise<string | null> => {
    const valid = await form.trigger();
    if (!valid) {
      // Jump to the first step that has an error.
      const errored = Object.keys(form.formState.errors);
      const firstStep = WIZARD_STEPS.findIndex((_, index) =>
        stepFields[index].some((field) => errored.includes(field as string)),
      );
      if (firstStep >= 0) setStep(firstStep);
      return null;
    }
    const values = form.getValues();
    setPersisting(true);
    const result = await persistProfileWithExtensions({
      savedProfile,
      extensionIds: values.extension_ids,
      saveProfile: async () => {
        if (mode === 'edit' && editingId) {
          return updateProfile.mutateAsync({
            id: editingId,
            payload: wizardValuesToPatch(values, profileQuery.data!),
          });
        }
        return createProfile.mutateAsync(wizardValuesToPayload(values));
      },
      updateSavedProfile: async (profile) => {
        const payload = wizardValuesToPatch(values, profile);
        if (Object.keys(payload).length === 1) return profile;
        return updateProfile.mutateAsync({ id: profile.id, payload });
      },
      assignExtensions: (profileId, extensionIds) =>
        api.setProfileExtensions(profileId, extensionIds),
    }).finally(() => setPersisting(false));
    if (!result.assignmentComplete) {
      setSavedProfile(result.profile);
      setAssignmentPending(true);
      return null;
    }
    setSavedProfile(null);
    setAssignmentPending(false);
    return result.profile.id;
  };

  const onSave = async () => {
    const id = await persist();
    if (id) navigate('/profiles');
  };

  const onSaveAndRun = async () => {
    const id = await persist();
    if (!id) return;
    try {
      await api.startProfile(id);
    } catch {
      // Start failures surface via events/runtime state on the list.
    }
    navigate('/profiles');
  };

  const CurrentStep = WIZARD_STEPS[step].Component;

  return (
    <FormProvider {...form}>
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <div>
            <h2 className="font-display text-[15px] font-semibold text-ink">
              {t(mode === 'edit' ? 'title.editProfile' : 'title.newProfile')}
            </h2>
            <p className="text-2xs text-ink-faint">
              {t('editor.stepProgress', {
                current: step + 1,
                total: WIZARD_STEPS.length,
                title: t(WIZARD_STEPS[step].titleKey),
              })}
            </p>
          </div>
          <IconButton label={t('editor.close')} onClick={() => navigate('/profiles')}>
            <X className="h-4 w-4" />
          </IconButton>
        </div>

        <div className="flex min-h-0 flex-1">
          <nav
            className="hidden w-56 shrink-0 overflow-y-auto border-r border-line p-3 md:block"
            aria-label={t('editor.steps')}
          >
            <ol className="space-y-0.5">
              {WIZARD_STEPS.map((wizardStep, index) => {
                const active = index === step;
                const done = index < step;
                return (
                  <li key={wizardStep.id}>
                    <button
                      type="button"
                      onClick={() => setStep(index)}
                      className={cn(
                        'flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left transition-colors',
                        active ? 'bg-accent/15' : 'hover:bg-surface-sunken',
                      )}
                    >
                      <span
                        className={cn(
                          'flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-2xs font-semibold',
                          active
                            ? 'border-accent bg-accent text-accent-fg'
                            : done
                              ? 'border-success/40 bg-success/15 text-success'
                              : 'border-line text-ink-faint',
                        )}
                      >
                        {done ? <Check className="h-3 w-3" /> : index + 1}
                      </span>
                      <span className="min-w-0">
                        <span
                          className={cn(
                            'block text-[13px] font-medium',
                            active ? 'text-ink' : 'text-ink-muted',
                          )}
                        >
                          {t(wizardStep.titleKey)}
                        </span>
                        <span className="block truncate text-2xs text-ink-faint">
                          {t(wizardStep.descKey)}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </nav>

          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto max-w-2xl px-5 py-6">
              <div className="mb-4">
                <h3 className="font-display text-base font-semibold text-ink">
                  {t(WIZARD_STEPS[step].titleKey)}
                </h3>
                <p className="text-[13px] text-ink-muted">{t(WIZARD_STEPS[step].descKey)}</p>
              </div>
              <CurrentStep refs={refs} />
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-line px-5 py-3">
          <Button
            variant="ghost"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
          >
            <ArrowLeft className="h-4 w-4" /> {t('common.back')}
          </Button>
          <div className="flex items-center gap-2">
            {assignmentPending && (
              <div
                role="alert"
                className="mr-2 flex max-w-md items-center gap-2 text-2xs text-warning"
              >
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <span>{t('editor.extensionAssignmentPartial')}</span>
                <Button size="sm" variant="ghost" loading={saving} onClick={onSave}>
                  {t('editor.retryExtensionAssignment')}
                </Button>
              </div>
            )}
            <Button variant="secondary" onClick={onSave} loading={saving}>
              <Save className="h-4 w-4" /> {t('common.save')}
            </Button>
            <Button variant="secondary" onClick={onSaveAndRun} loading={saving}>
              <Play className="h-4 w-4" /> {t('editor.saveRun')}
            </Button>
            {!isLast && (
              <Button variant="primary" onClick={goNext}>
                {t('common.next')} <ArrowRight className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
      </div>
    </FormProvider>
  );
}
