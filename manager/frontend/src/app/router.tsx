import type { ReactElement } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppLayout } from '@/layouts/AppLayout';
import { ProfilesPage } from '@/features/profiles/ProfilesPage';
import { ProfileWizardPage } from '@/features/profile-editor/ProfileWizardPage';
import { ProxiesPage } from '@/features/proxies/ProxiesPage';
import { FoldersPage } from '@/features/folders/FoldersPage';
import { DiagnosticsPage } from '@/features/diagnostics/DiagnosticsPage';
import { ResourcesPage } from '@/features/diagnostics/ResourcesPage';
import { AutomationPage } from '@/features/automation/AutomationPage';
import { ShopifyPage } from '@/features/shopify/ShopifyPage';
import { SettingsPage } from '@/features/settings/SettingsPage';
import { EmptyState } from '@/components/ui/states';
import { useCapabilities } from '@/hooks/useAppData';
import type { AppCapabilities } from '@/types/api';
import { useT } from '@/i18n';

/** Redirects to Profiles when the backend reports the capability off, so a
 * bookmarked URL to a disabled screen degrades gracefully instead of erroring. */
function RequireCapability({
  cap,
  children,
}: {
  cap: keyof AppCapabilities;
  children: ReactElement;
}) {
  const capabilities = useCapabilities();
  if (!capabilities[cap]) return <Navigate to="/profiles" replace />;
  return children;
}

function NotFound() {
  const t = useT();
  return (
    <div className="grid h-full place-items-center">
      <EmptyState title={t('nav.notFound.title')} description={t('nav.notFound.desc')} />
    </div>
  );
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/profiles" replace /> },
      { path: 'profiles', element: <ProfilesPage /> },
      { path: 'profiles/new', element: <ProfileWizardPage mode="create" /> },
      { path: 'profiles/:id/edit', element: <ProfileWizardPage mode="edit" /> },
      {
        path: 'folders',
        element: (
          <RequireCapability cap="catalogs">
            <FoldersPage />
          </RequireCapability>
        ),
      },
      {
        path: 'proxies',
        element: (
          <RequireCapability cap="proxy_management">
            <ProxiesPage />
          </RequireCapability>
        ),
      },
      {
        path: 'diagnostics',
        element: (
          <RequireCapability cap="fingerprint_diagnostics">
            <DiagnosticsPage />
          </RequireCapability>
        ),
      },
      {
        path: 'resources',
        element: (
          <RequireCapability cap="browser_runtime">
            <ResourcesPage />
          </RequireCapability>
        ),
      },
      {
        path: 'automation',
        element: (
          <RequireCapability cap="automation">
            <AutomationPage />
          </RequireCapability>
        ),
      },
      {
        path: 'shopify',
        element: (
          <RequireCapability cap="shopify_builder">
            <ShopifyPage />
          </RequireCapability>
        ),
      },
      {
        path: 'settings',
        element: (
          <RequireCapability cap="settings">
            <SettingsPage />
          </RequireCapability>
        ),
      },
      { path: '*', element: <NotFound /> },
    ],
  },
]);
