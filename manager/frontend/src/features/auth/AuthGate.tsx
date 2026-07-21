import type { ReactNode } from 'react';
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
      <Centered>
        <LoadingBlock label={t('auth.checking')} />
      </Centered>
    );
  }

  return <AuthScreen mode={setupRequired ? 'setup' : 'login'} />;
}

function Centered({ children }: { children: ReactNode }) {
  return <div className="grid h-screen place-items-center bg-canvas text-ink">{children}</div>;
}

interface FormValues {
  email: string;
  password: string;
  confirm: string;
}

function AuthScreen({ mode }: { mode: 'setup' | 'login' }) {
  const t = useT();
  const login = useLogin();
  const setup = useSetup();
  const isSetup = mode === 'setup';
  const pending = login.isPending || setup.isPending;
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<FormValues>({ defaultValues: { email: '', password: '', confirm: '' } });

  const serverError = (login.error ?? setup.error) as ApiError | null;

  const onSubmit = handleSubmit((values) => {
    const payload = { email: values.email, password: values.password };
    (isSetup ? setup : login).mutate(payload);
  });

  return (
    <div className="grid h-screen place-items-center bg-canvas px-4 text-ink">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <LogoMark size={30} />
            <span className="font-display text-[15px] font-semibold">{t('auth.appName')}</span>
          </div>
          <LanguageToggle />
        </div>

        <div className="rounded-xl border border-line bg-surface p-6 shadow-panel">
          <div className="mb-4 flex items-center gap-2">
            {isSetup ? (
              <ShieldCheck className="h-5 w-5 text-accent" />
            ) : (
              <LogIn className="h-5 w-5 text-accent" />
            )}
            <h1 className="font-display text-lg font-semibold">
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
              <Field label={t('auth.confirmPassword')} error={errors.confirm && t('auth.mismatch')}>
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
      </div>
    </div>
  );
}
