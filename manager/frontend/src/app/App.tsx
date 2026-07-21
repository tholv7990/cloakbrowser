import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router-dom';
import { createQueryClient } from './queryClient';
import { router } from './router';
import { ThemeManager } from './ThemeManager';
import { RealtimeProvider } from '@/realtime/RealtimeProvider';
import { ToastProvider } from '@/components/ui/Toast';
import { AuthGate } from '@/features/auth/AuthGate';

const queryClient = createQueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <ThemeManager />
        <AuthGate>
          <RealtimeProvider>
            <RouterProvider router={router} />
          </RealtimeProvider>
        </AuthGate>
      </ToastProvider>
    </QueryClientProvider>
  );
}
