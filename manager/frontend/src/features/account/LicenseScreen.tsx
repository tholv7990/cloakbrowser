import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { KeyRound, LogIn, ShieldAlert, ShieldCheck } from 'lucide-react';
import { LogoMark } from '@/components/Logo';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { LoadingBlock } from '@/components/ui/states';
import { LanguageToggle } from '@/components/LanguageToggle';
import { ApiError } from '@/api';
import { useT } from '@/i18n';
import type { LicenseStatus } from '@/types/api';
import { AuthBackground } from '@/features/auth/AuthBackground';
import {
  useAccount,
  useAccountActivate,
  useAccountLogin,
  useAccountLogout,
  useAccountRegister,
} from './api';

/**
 * Shown when the backend reports the license is not usable. Two steps: sign in to
 * the Plasma account, then activate a key. The headline reflects why we're here
 * (expired vs. never activated vs. a verification problem).
 */
export function LicenseScreen({ license }: { license: LicenseStatus }) {
  const t = useT();
  const account = useAccount();

  return (
    <div className="grid h-screen w-full lg:grid-cols-[1.1fr_1fr]">
      <div className="relative hidden overflow-hidden lg:block">
        <AuthBackground imageUrl={import.meta.env.VITE_AUTH_BG_URL} />
        <div className="relative z-10 flex h-full flex-col justify-between p-10 text-white">
          <div className="flex items-center gap-2.5">
            <LogoMark size={32} />
            <span className="font-display text-[15px] font-semibold">Plasma</span>
          </div>
          <div className="max-w-md">
            <h2 className="font-display text-[32px] font-semibold leading-[1.15]">
              {t('account.heroTitle')}
            </h2>
            <p className="mt-4 text-[15px] leading-relaxed text-white/70">
              {t('account.heroSubtext')}
            </p>
          </div>
          <p className="text-2xs uppercase tracking-[0.14em] text-white/45">
            {t('auth.brandFooter')}
          </p>
        </div>
      </div>

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

          {account.isLoading ? (
            <div className="rounded-xl border border-line bg-surface p-6 shadow-panel">
              <LoadingBlock label={t('account.checking')} />
            </div>
          ) : account.data?.signed_in ? (
            <ActivatePanel license={license} email={account.data.email} />
          ) : (
            <SignedOut license={license} />
          )}
        </div>
      </div>
    </div>
  );
}

interface LoginValues {
  email: string;
  password: string;
}

function SignInPanel({ license }: { license: LicenseStatus }) {
  const t = useT();
  const login = useAccountLogin();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginValues>({ defaultValues: { email: '', password: '' } });

  const onSubmit = handleSubmit((values) => login.mutate(values));
  const serverError = login.error as ApiError | null;

  return (
    <div className="rounded-xl border border-line bg-surface p-6 shadow-panel">
      <PanelHeading state={license.state} step="signin" />
      <form onSubmit={onSubmit} className="space-y-3">
        <Field label={t('auth.email')} error={errors.email && t('account.required')}>
          <Input
            type="email"
            autoComplete="username"
            autoFocus
            {...register('email', { required: true })}
            invalid={Boolean(errors.email)}
          />
        </Field>
        <Field label={t('auth.password')} error={errors.password && t('account.required')}>
          <Input
            type="password"
            autoComplete="current-password"
            {...register('password', { required: true })}
            invalid={Boolean(errors.password)}
          />
        </Field>
        {serverError && <p className="text-2xs text-danger">{serverError.message}</p>}
        <Button type="submit" variant="primary" className="w-full" loading={login.isPending}>
          {t('account.signIn')}
        </Button>
      </form>
    </div>
  );
}

interface ActivateValues {
  activation_key: string;
}

function ActivatePanel({
  license,
  email,
}: {
  license: LicenseStatus;
  email: string | null;
}) {
  const t = useT();
  const activate = useAccountActivate();
  const logout = useAccountLogout();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ActivateValues>({ defaultValues: { activation_key: '' } });

  const onSubmit = handleSubmit((values) =>
    activate.mutate({ activation_key: values.activation_key.trim() }),
  );
  const serverError = activate.error as ApiError | null;

  return (
    <div className="rounded-xl border border-line bg-surface p-6 shadow-panel">
      <PanelHeading state={license.state} step="activate" />
      <form onSubmit={onSubmit} className="space-y-3">
        <Field label={t('account.keyLabel')} hint={t('account.keyHint')}>
          <Input
            autoFocus
            spellCheck={false}
            autoCapitalize="characters"
            placeholder="PLASMA-XXXX-XXXX-XXXX"
            {...register('activation_key', { required: true })}
            invalid={Boolean(errors.activation_key)}
          />
        </Field>
        {serverError && <p className="text-2xs text-danger">{serverError.message}</p>}
        <Button type="submit" variant="primary" className="w-full" loading={activate.isPending}>
          {t('account.activate')}
        </Button>
      </form>

      <div className="mt-4 flex items-center justify-between border-t border-line pt-3 text-2xs text-ink-muted">
        <span className="truncate">{email ? t('account.signedInAs', { email }) : ''}</span>
        <button
          type="button"
          className="shrink-0 font-medium text-ink-muted transition hover:text-ink"
          onClick={() => logout.mutate()}
          disabled={logout.isPending}
        >
          {t('account.signOut')}
        </button>
      </div>
    </div>
  );
}

function PanelHeading({
  state,
  step,
}: {
  state: LicenseStatus['state'];
  step: 'signin' | 'activate';
}) {
  const t = useT();
  const expired = state === 'expired';
  const invalid = state === 'invalid';

  const Icon = expired || invalid ? ShieldAlert : step === 'signin' ? LogIn : ShieldCheck;
  const tone = expired || invalid ? 'text-danger' : 'text-accent';
  const titleKey =
    step === 'signin'
      ? 'account.signInTitle'
      : expired
        ? 'account.expiredTitle'
        : invalid
          ? 'account.invalidTitle'
          : 'account.activateTitle';
  const subtitleKey =
    step === 'signin'
      ? 'account.signInSubtitle'
      : expired
        ? 'account.expiredSubtitle'
        : invalid
          ? 'account.invalidSubtitle'
          : 'account.activateSubtitle';

  return (
    <div className="mb-4">
      <div className="mb-1.5 flex items-center gap-2">
        {step === 'activate' && !expired && !invalid ? (
          <KeyRound className={`h-5 w-5 ${tone}`} />
        ) : (
          <Icon className={`h-5 w-5 ${tone}`} />
        )}
        <h1 className="font-display text-lg font-semibold text-ink">{t(titleKey)}</h1>
      </div>
      <p className="text-[13px] leading-relaxed text-ink-muted">{t(subtitleKey)}</p>
    </div>
  );
}

function SignedOut({ license }: { license: LicenseStatus }) {
  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const t = useT();
  return mode === 'signin' ? (
    <div className="space-y-3">
      <SignInPanel license={license} />
      <button
        type="button"
        className="w-full text-center text-2xs font-medium text-ink-muted transition hover:text-ink"
        onClick={() => setMode('signup')}
      >
        {t('account.needAccount')}
      </button>
    </div>
  ) : (
    <SignUpPanel license={license} onSwitch={() => setMode('signin')} />
  );
}

interface SignUpValues {
  email: string;
  password: string;
  confirm: string;
}

export function SignUpPanel({
  license,
  onSwitch,
}: {
  license: LicenseStatus;
  onSwitch: () => void;
}) {
  const t = useT();
  const registerMut = useAccountRegister();
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<SignUpValues>({ defaultValues: { email: '', password: '', confirm: '' } });

  const onSubmit = handleSubmit((values) =>
    registerMut.mutate({ email: values.email, password: values.password }),
  );
  const serverError = registerMut.error as ApiError | null;

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-line bg-surface p-6 shadow-panel">
        <div className="mb-4">
          <div className="mb-1.5 flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-accent" />
            <h1 className="font-display text-lg font-semibold text-ink">{t('account.signUpTitle')}</h1>
          </div>
          <p className="text-[13px] leading-relaxed text-ink-muted">{t('account.signUpSubtitle')}</p>
        </div>
        <form onSubmit={onSubmit} className="space-y-3">
          <Field label={t('auth.email')} error={errors.email && t('account.required')}>
            <Input
              type="email"
              autoComplete="username"
              autoFocus
              aria-label={t('auth.email')}
              {...register('email', { required: true })}
              invalid={Boolean(errors.email)}
            />
          </Field>
          <Field
            label={t('auth.password')}
            hint={t('auth.passwordHint')}
            error={errors.password && t('auth.passwordHint')}
          >
            <Input
              type="password"
              autoComplete="new-password"
              aria-label={t('auth.password')}
              {...register('password', { required: true, minLength: 12 })}
              invalid={Boolean(errors.password)}
            />
          </Field>
          <Field label={t('auth.confirmPassword')} error={errors.confirm && t('auth.mismatch')}>
            <Input
              type="password"
              autoComplete="new-password"
              aria-label={t('auth.confirmPassword')}
              {...register('confirm', { validate: (value) => value === watch('password') })}
              invalid={Boolean(errors.confirm)}
            />
          </Field>
          {serverError && <p className="text-2xs text-danger">{serverError.message}</p>}
          <Button type="submit" variant="primary" className="w-full" loading={registerMut.isPending}>
            {t('account.signUp')}
          </Button>
        </form>
      </div>
      <button
        type="button"
        className="w-full text-center text-2xs font-medium text-ink-muted transition hover:text-ink"
        onClick={onSwitch}
      >
        {t('account.haveAccount')}
      </button>
    </div>
  );
}
