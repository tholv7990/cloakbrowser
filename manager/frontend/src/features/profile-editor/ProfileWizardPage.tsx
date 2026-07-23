import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { FormProvider, useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { AlertTriangle, Play, Save, X } from 'lucide-react';
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
import { useCreateProfile, useProfile, useProfileExtensions, useUpdateProfile } from './api';
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
  const profileExtensionsQuery = useProfileExtensions(editingId);
  const createProfile = useCreateProfile();
  const updateProfile = useUpdateProfile();

  const [activeId, setActiveId] = useState(WIZARD_STEPS[0].id);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [savedProfile, setSavedProfile] = useState<ProfileRead | null>(null);
  const [assignmentPending, setAssignmentPending] = useState(false);
  const [persisting, setPersisting] = useState(false);

  const scrollToSection = (id: string) => {
    document.getElementById(`sec-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const form = useForm<ProfileWizardValues>({
    resolver: zodResolver(profileWizardSchema),
    defaultValues: defaultWizardValues(),
    mode: 'onBlur',
  });

  // Load an existing profile into the form once (edit mode).
  useEffect(() => {
    if (mode === 'edit' && profileQuery.data && profileExtensionsQuery.data) {
      form.reset(
        profileToWizardValues(profileQuery.data, profileExtensionsQuery.data.extension_ids),
      );
    }
  }, [mode, profileQuery.data, profileExtensionsQuery.data, form]);

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

  const editBusy =
    mode === 'edit' &&
    (profileQuery.isLoading ||
      profileExtensionsQuery.isLoading ||
      profileQuery.isError ||
      profileExtensionsQuery.isError);
  const contentReady = !app.isLoading && !app.isError && !editBusy;

  // Scroll-spy: highlight the section currently at the top of the form.
  useEffect(() => {
    const root = scrollRef.current;
    if (!contentReady || !root) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((entry) => entry.isIntersecting);
        if (visible.length === 0) return;
        const topmost = visible.reduce((a, b) =>
          a.boundingClientRect.top <= b.boundingClientRect.top ? a : b,
        );
        setActiveId(topmost.target.id.replace('sec-', ''));
      },
      { root, rootMargin: '0px 0px -65% 0px', threshold: 0 },
    );
    for (const wizardStep of WIZARD_STEPS) {
      const element = document.getElementById(`sec-${wizardStep.id}`);
      if (element) observer.observe(element);
    }
    return () => observer.disconnect();
  }, [contentReady]);

  if (
    app.isLoading ||
    (mode === 'edit' && (profileQuery.isLoading || profileExtensionsQuery.isLoading))
  ) {
    return <LoadingBlock label={t('editor.loading')} />;
  }
  if (app.isError) {
    return <ErrorState message={t('editor.loadError')} onRetry={() => window.location.reload()} />;
  }
  if (mode === 'edit' && (profileQuery.isError || profileExtensionsQuery.isError)) {
    return (
      <ErrorState
        message={t('editor.loadProfileError')}
        onRetry={() => {
          profileQuery.refetch();
          profileExtensionsQuery.refetch();
        }}
      />
    );
  }

  const saving = createProfile.isPending || updateProfile.isPending || persisting;

  const persist = async (): Promise<string | null> => {
    const valid = await form.trigger();
    if (!valid) {
      // Scroll to the first section that has an error.
      const errored = Object.keys(form.formState.errors);
      const firstStep = WIZARD_STEPS.findIndex((_, index) =>
        stepFields[index].some((field) => errored.includes(field as string)),
      );
      if (firstStep >= 0) scrollToSection(WIZARD_STEPS[firstStep].id);
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

  return (
    <FormProvider {...form}>
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <h2 className="font-display text-[15px] font-semibold text-ink">
            {t(mode === 'edit' ? 'title.editProfile' : 'title.newProfile')}
          </h2>
          <IconButton label={t('editor.close')} onClick={() => navigate('/profiles')}>
            <X className="h-4 w-4" />
          </IconButton>
        </div>

        <div className="flex min-h-0 flex-1">
          <nav
            className="hidden w-52 shrink-0 overflow-y-auto border-r border-line p-3 md:block"
            aria-label={t('editor.steps')}
          >
            <ul className="space-y-0.5">
              {WIZARD_STEPS.map((wizardStep) => {
                const active = activeId === wizardStep.id;
                return (
                  <li key={wizardStep.id}>
                    <button
                      type="button"
                      onClick={() => scrollToSection(wizardStep.id)}
                      className={cn(
                        'flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left transition-colors',
                        active ? 'bg-accent/15 text-ink' : 'text-ink-muted hover:bg-surface-sunken',
                      )}
                    >
                      <span
                        className={cn(
                          'h-1.5 w-1.5 shrink-0 rounded-full transition-colors',
                          active ? 'bg-accent' : 'bg-line-strong',
                        )}
                      />
                      <span className="text-[13px] font-medium">{t(wizardStep.titleKey)}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>

          <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto max-w-2xl space-y-10 px-5 py-6">
              {WIZARD_STEPS.map((wizardStep) => {
                const Section = wizardStep.Component;
                return (
                  <section key={wizardStep.id} id={`sec-${wizardStep.id}`} className="scroll-mt-4">
                    <div className="mb-4">
                      <h3 className="font-display text-base font-semibold text-ink">
                        {t(wizardStep.titleKey)}
                      </h3>
                      <p className="text-[13px] text-ink-muted">{t(wizardStep.descKey)}</p>
                    </div>
                    <Section refs={refs} />
                  </section>
                );
              })}
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-line px-5 py-3">
          {assignmentPending && (
            <div role="alert" className="mr-auto flex max-w-md items-center gap-2 text-2xs text-warning">
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
          <Button variant="primary" onClick={onSaveAndRun} loading={saving}>
            <Play className="h-4 w-4" /> {t('editor.saveRun')}
          </Button>
        </div>
      </div>
    </FormProvider>
  );
}
