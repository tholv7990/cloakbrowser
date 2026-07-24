import type { ReactNode } from 'react';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { LogIn, ShieldCheck } from 'lucide-react';
import { LogoMark } from '@/components/Logo';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { LoadingBlock } from '@/components/ui/states';
import { ApiError } from '@/api';
import { useT } from '@/i18n';
import { LanguageToggle } from '@/components/LanguageToggle';
import { AuthBackground } from './AuthBackground';
import { useAuthSession, useAuthStatus, useLogin, useSetup } from './api';

/**
 * Gates the whole app behind the local owner login (spec §3). Authentication is
 * derived from the session query, so signing out (which clears the cache) lands
 * back on the login screen automatically.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const t = useT();
  const status = useAuthStatus();
  const setupRequired = status.data?.setup_required ?? false;
  const session = useAuthSession(Boolean(status.data) && !setupRequired);
  const authed = Boolean(session.data);

  if (authed) return <>{children}</>;

  if (status.isLoading || (!setupRequired && session.isLoading)) {
    return (
      <div className="grid h-screen place-items-center bg-canvas text-ink">
        <LoadingBlock label={t('auth.checking')} />
      </div>
    );
  }

  return <AuthScreen initialMode={setupRequired ? 'setup' : 'login'} />;
}

interface FormValues {
  email: string;
  password: string;
  confirm: string;
}

export function AuthScreen({ initialMode }: { initialMode: 'setup' | 'login' }) {
  const t = useT();
  const [mode, setMode] = useState<'setup' | 'login'>(initialMode);
  const login = useLogin();
  const setup = useSetup();
  const isSetup = mode === 'setup';
  const pending = login.isPending || setup.isPending;
  const backgroundUrl = import.meta.env.VITE_AUTH_BG_URL;
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<FormValues>({ defaultValues: { email: '', password: '', confirm: '' } });

  const serverError = (login.error ?? setup.error) as ApiError | null;

  const onSubmit = handleSubmit((values) => {
    (isSetup ? setup : login).mutate({ email: values.email, password: values.password });
  });

  return (
    <div className="grid h-screen w-full lg:grid-cols-[1.1fr_1fr]">
      {/* Brand + image hero (desktop) */}
      <div className="relative hidden overflow-hidden lg:block">
        <AuthBackground imageUrl={backgroundUrl} />
        <div className="relative z-10 flex h-full flex-col justify-between p-10 text-white">
          <div className="flex items-center gap-2.5">
            <LogoMark size={32} />
            <span className="font-display text-[15px] font-semibold">Plasma</span>
          </div>
          <div className="max-w-md">
            <h2 className="font-display text-[32px] font-semibold leading-[1.15]">
              {t('auth.brandTagline')}
            </h2>
            <p className="mt-4 text-[15px] leading-relaxed text-white/70">
              {t('auth.brandSubtext')}
            </p>
          </div>
          <p className="text-2xs uppercase tracking-[0.14em] text-white/45">
            {t('auth.brandFooter')}
          </p>
        </div>
      </div>

      {/* Form panel */}
      <div className="relative flex items-center justify-center bg-canvas px-6 py-10">
        <div className="w-full max-w-sm">
          <div className="mb-5 flex items-center justify-between">
            <div className="flex items-center gap-2.5 lg:hidden">
              <LogoMark size={26} />
              <span className="font-display text-[14px] font-semibold text-ink">Plasma</span>
            </div>
            <div className="hidden lg:block" />
            <LanguageToggle />
          </div>

          <div className="rounded-xl border border-line bg-surface p-6 shadow-panel">
            <div className="mb-4 flex items-center gap-2">
              {isSetup ? (
                <ShieldCheck className="h-5 w-5 text-accent" />
              ) : (
                <LogIn className="h-5 w-5 text-accent" />
              )}
              <h1 className="font-display text-lg font-semibold text-ink">
                {t(isSetup ? 'auth.setupTitle' : 'auth.loginTitle')}
              </h1>
            </div>
            <p className="mb-5 text-[13px] text-ink-muted">
              {t(isSetup ? 'auth.setupSubtitle' : 'auth.loginSubtitle')}
            </p>

            <form onSubmit={onSubmit} className="space-y-3">
              <Field label={t('auth.email')} error={errors.email && 'Required'}>
                <Input
                  type="email"
                  autoComplete="username"
                  autoFocus
                  {...register('email', { required: true })}
                  invalid={Boolean(errors.email)}
                />
              </Field>
              <Field
                label={t('auth.password')}
                hint={isSetup ? t('auth.passwordHint') : undefined}
                error={errors.password && t('auth.passwordHint')}
              >
                <Input
                  type="password"
                  autoComplete={isSetup ? 'new-password' : 'current-password'}
                  {...register('password', { required: true, minLength: isSetup ? 12 : 1 })}
                  invalid={Boolean(errors.password)}
                />
              </Field>
              {isSetup && (
                <Field
                  label={t('auth.confirmPassword')}
                  error={errors.confirm && t('auth.mismatch')}
                >
                  <Input
                    type="password"
                    autoComplete="new-password"
                    {...register('confirm', { validate: (value) => value === watch('password') })}
                    invalid={Boolean(errors.confirm)}
                  />
                </Field>
              )}
              {serverError && <p className="text-2xs text-danger">{serverError.message}</p>}
              <Button type="submit" variant="primary" className="w-full" loading={pending}>
                {t(isSetup ? 'auth.createAccount' : 'auth.signIn')}
              </Button>
            </form>
          </div>
          <button
            type="button"
            className="mt-4 w-full text-center text-2xs font-medium text-ink-muted transition hover:text-ink"
            onClick={() => setMode(isSetup ? 'login' : 'setup')}
          >
            {t(isSetup ? 'auth.toSignIn' : 'auth.toCreate')}
          </button>
        </div>
      </div>
    </div>
  );
}
