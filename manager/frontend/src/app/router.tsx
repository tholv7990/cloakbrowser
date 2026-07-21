import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppLayout } from '@/layouts/AppLayout';
import { ProfilesPage } from '@/features/profiles/ProfilesPage';
import { ProfileWizardPage } from '@/features/profile-editor/ProfileWizardPage';
import { ProxiesPage } from '@/features/proxies/ProxiesPage';
import { FoldersPage } from '@/features/folders/FoldersPage';
import { DiagnosticsPage } from '@/features/diagnostics/DiagnosticsPage';
import { SettingsPage } from '@/features/settings/SettingsPage';
import { EmptyState } from '@/components/ui/states';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/profiles" replace /> },
      { path: 'profiles', element: <ProfilesPage /> },
      { path: 'profiles/new', element: <ProfileWizardPage mode="create" /> },
      { path: 'profiles/:id/edit', element: <ProfileWizardPage mode="edit" /> },
      { path: 'folders', element: <FoldersPage /> },
      { path: 'proxies', element: <ProxiesPage /> },
      { path: 'diagnostics', element: <DiagnosticsPage /> },
      { path: 'settings', element: <SettingsPage /> },
      {
        path: '*',
        element: (
          <div className="grid h-full place-items-center">
            <EmptyState
              title="Page not found"
              description="That screen does not exist in the manager."
            />
          </div>
        ),
      },
    ],
  },
]);
