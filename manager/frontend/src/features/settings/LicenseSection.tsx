import { LogOut, RefreshCw } from 'lucide-react';
import type { LicenseStatus } from '@/types/api';
import { Badge, type Tone } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/Toast';
import { formatDateTime } from '@/lib/format';
import { useT } from '@/i18n';
import {
  useAccount,
  useAccountLogout,
  useAccountRefresh,
  useLicense,
} from '@/features/account/api';

const STATE_TONES: Record<LicenseStatus['state'], Tone> = {
  disabled: 'neutral',
  active: 'success',
  grace: 'warning',
  unlicensed: 'warning',
  expired: 'danger',
  invalid: 'danger',
};

const fromEpoch = (seconds: number | null) =>
  seconds == null ? null : formatDateTime(new Date(seconds * 1000).toISOString());

/**
 * Plasma license + cloud account status once the user is past the LicenseGate.
 * Read-only view of GET /license + GET /account with Refresh and Sign out.
 */
export function LicenseSection() {
  const t = useT();
  const license = useLicense();
  const account = useAccount();
  const refresh = useAccountRefresh();
  const logout = useAccountLogout();
  const { toast } = useToast();

  const lic = license.data;
  const acct = account.data;
  // ponytail: no loading/error skeleton — these are fast local calls and the
  // gate already surfaced any hard failure before Settings is reachable.
  if (!lic || !acct) return null;

  const expires = fromEpoch(lic.expires_at);
  const grace = fromEpoch(lic.grace_deadline);
  const actionError = (refresh.error ?? logout.error) as Error | null;

  return (
    <section className="rounded-lg border border-line bg-surface p-4">
      <h2 className="font-display text-[15px] font-semibold text-ink">{t('settings.license')}</h2>
      <p className="mt-0.5 text-2xs text-ink-faint">{t('settings.license.desc')}</p>

      <div className="mt-3 space-y-3">
        <div className="flex items-center gap-2">
          <Badge tone={STATE_TONES[lic.state]}>{t(`settings.license.state.${lic.state}`)}</Badge>
          {lic.plan && <Badge tone="accent">{lic.plan}</Badge>}
          {(expires || grace) && (
            <span className="text-2xs text-ink-muted">
              {expires && t('settings.license.expires', { time: expires })}
              {expires && grace && ' · '}
              {grace && t('settings.license.grace', { time: grace })}
            </span>
          )}
        </div>
        {lic.detail && <p className="data text-2xs text-ink-faint">{lic.detail}</p>}

        <div className="flex items-center justify-between gap-3 rounded-md border border-line bg-surface-sunken px-3 py-2.5">
          <span className="truncate text-[13px] text-ink">
            {acct.signed_in && acct.email
              ? t('account.signedInAs', { email: acct.email })
              : t('settings.license.notSignedIn')}
          </span>
          {acct.signed_in && (
            <div className="flex shrink-0 gap-2">
              <Button
                variant="secondary"
                size="sm"
                loading={refresh.isPending}
                onClick={() =>
                  refresh.mutate(undefined, {
                    onSuccess: () =>
                      toast({ title: t('settings.license.refreshed'), tone: 'success' }),
                  })
                }
              >
                <RefreshCw className="h-3.5 w-3.5" /> {t('settings.license.refresh')}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                loading={logout.isPending}
                onClick={() => logout.mutate()}
              >
                <LogOut className="h-3.5 w-3.5" /> {t('account.signOut')}
              </Button>
            </div>
          )}
        </div>
        {actionError && <p className="text-2xs text-danger">{actionError.message}</p>}
      </div>
    </section>
  );
}
