import type { ReactNode } from 'react';
import { LoadingBlock } from '@/components/ui/states';
import { useT } from '@/i18n';
import { useLicense } from './api';
import { LicenseScreen } from './LicenseScreen';

/**
 * Gates the app on a valid license. Only bites in a licensed build — a free/dev
 * backend reports state 'disabled' (allowed: true), so this is a pass-through. The
 * backend is the real enforcement (it blocks launches server-side), so on a loading
 * error we render the app rather than lock the UI on a transient hiccup.
 */
export function LicenseGate({ children }: { children: ReactNode }) {
  const t = useT();
  const license = useLicense();

  if (license.isLoading) {
    return (
      <div className="grid h-screen place-items-center bg-canvas text-ink">
        <LoadingBlock label={t('account.checking')} />
      </div>
    );
  }

  if (license.data && !license.data.allowed) {
    return <LicenseScreen license={license.data} />;
  }

  return <>{children}</>;
}
