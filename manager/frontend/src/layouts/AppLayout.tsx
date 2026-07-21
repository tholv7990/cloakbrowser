import { Outlet } from 'react-router-dom';
import { WifiOff } from 'lucide-react';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { useRealtime } from '@/realtime/RealtimeProvider';
import { useT } from '@/i18n';

export function AppLayout() {
  const t = useT();
  const { connectionState } = useRealtime();
  const disconnected = connectionState === 'disconnected' || connectionState === 'reconnecting';

  return (
    <div className="flex h-screen overflow-hidden bg-canvas text-ink">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        {disconnected && (
          <div
            role="status"
            className="flex items-center gap-2 border-b border-warning/30 bg-warning/10 px-5 py-2 text-2xs text-warning"
          >
            <WifiOff className="h-3.5 w-3.5" />
            {t('conn.lost')}
          </div>
        )}
        <main className="min-h-0 flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
