import { useState, useEffect } from 'react';
import { LayoutGrid, Users, Key, CreditCard, Download, FileText, LogOut } from 'lucide-react';
import { LoginPage } from './LoginPage';
import { OverviewScreen } from './screens/Overview';
import { UsersScreen } from './screens/Users';
import { UserDetailScreen } from './screens/UserDetail';
import { LicencesScreen } from './screens/Licences';
import { PlansScreen } from './screens/Plans';
import { ReleasesScreen } from './screens/Releases';
import { AuditScreen } from './screens/Audit';

type Screen = 'overview' | 'users' | 'user' | 'licences' | 'plans' | 'releases' | 'audit';

export function App() {
  const [currentScreen, setCurrentScreen] = useState<Screen>('overview');
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState('');
  const [isLoggedIn, setIsLoggedIn] = useState(() => !!sessionStorage.getItem('plasma_admin_token'));

  useEffect(() => {
    if (isLoggedIn) {
      const email = sessionStorage.getItem('plasma_admin_email');
      if (email) setUserEmail(email);
    }
  }, [isLoggedIn]);

  function handleLogin(email: string) {
    setUserEmail(email);
    setIsLoggedIn(true);
    setCurrentScreen('overview');
  }

  function handleLogout() {
    sessionStorage.removeItem('plasma_admin_token');
    sessionStorage.removeItem('plasma_admin_email');
    setIsLoggedIn(false);
    setCurrentScreen('overview');
  }

  function handleSelectUser(id: string) {
    setSelectedUserId(id);
    setCurrentScreen('user');
  }

  if (!isLoggedIn) {
    return <LoginPage onLogin={handleLogin} />;
  }

  function navigate(screen: Screen) {
    setSelectedUserId(null);
    setCurrentScreen(screen);
  }

  const navItems: Array<{ id: Screen; label: string; icon: React.ReactNode }> = [
    { id: 'overview', label: 'Overview', icon: <LayoutGrid className="h-4 w-4" /> },
    { id: 'users', label: 'Users', icon: <Users className="h-4 w-4" /> },
    { id: 'licences', label: 'Licences', icon: <Key className="h-4 w-4" /> },
    { id: 'plans', label: 'Plans', icon: <CreditCard className="h-4 w-4" /> },
    { id: 'releases', label: 'Releases', icon: <Download className="h-4 w-4" /> },
    { id: 'audit', label: 'Audit', icon: <FileText className="h-4 w-4" /> },
  ];

  const isActive = (id: Screen) =>
    currentScreen === id || (id === 'users' && currentScreen === 'user');

  const logo = (
    <svg width="26" height="26" viewBox="0 0 32 32" fill="none">
      <path d="M16 2.5 27 6.2v8.3c0 7.2-4.6 12.9-11 15.5-6.4-2.6-11-8.3-11-15.5V6.2L16 2.5Z"
            fill="rgb(91 155 245 / .15)" stroke="rgb(91 155 245)" strokeWidth="1.6"/>
      <path d="M16 9.2c3.4 0 6.2 2.9 6.2 6.4 0 1.4-.4 2.6-1.1 3.7-1.2-2.6-3-4-5.1-4-2.6 0-4.2 1.9-4.2 4.4 0 .5.1 1 .2 1.4A6.4 6.4 0 0 1 9.8 15.6c0-3.5 2.8-6.4 6.2-6.4Z"
            fill="rgb(91 155 245)"/>
    </svg>
  );

  const screen = (
    <>
      {currentScreen === 'overview' && <OverviewScreen />}
      {currentScreen === 'users' && <UsersScreen onSelectUser={handleSelectUser} />}
      {currentScreen === 'user' && selectedUserId && (
        <UserDetailScreen
          userId={selectedUserId}
          onBack={() => setCurrentScreen('users')}
        />
      )}
      {currentScreen === 'licences' && <LicencesScreen />}
      {currentScreen === 'plans' && <PlansScreen />}
      {currentScreen === 'releases' && <ReleasesScreen />}
      {currentScreen === 'audit' && <AuditScreen />}
    </>
  );

  return (
    <div className="flex h-screen flex-col bg-canvas lg:flex-row">
      {/* Phone/tablet: compact top bar; the sidebar takes over at lg. */}
      <header className="flex shrink-0 items-center gap-3 border-b border-line bg-surface px-4 py-2.5 lg:hidden">
        {logo}
        <div className="min-w-0">
          <div className="text-sm font-bold leading-tight text-ink">Plasma</div>
          <div className="truncate text-2xs text-ink-muted">{userEmail}</div>
        </div>
        <button
          onClick={handleLogout}
          title="Sign out"
          className="ml-auto inline-flex h-10 w-10 items-center justify-center rounded text-ink-muted transition-colors hover:bg-surface-raised hover:text-ink"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </header>

      <aside className="hidden w-64 border-r border-line bg-surface lg:block">
        <div className="flex h-full flex-col gap-6 p-6">
          <div className="flex items-center gap-3">
            {logo}
            <div>
              <div className="text-sm font-bold text-ink">Plasma</div>
              <div className="text-2xs uppercase tracking-wider text-ink-muted">Super Admin</div>
            </div>
          </div>

          <nav className="flex flex-col gap-1">
            {navItems.map((item) => (
              <button
                key={item.id}
                onClick={() => navigate(item.id)}
                className={`flex items-center gap-3 rounded px-3 py-2 text-sm font-medium transition-colors ${
                  isActive(item.id)
                    ? 'bg-surface-raised text-accent'
                    : 'text-ink-muted hover:bg-surface-raised hover:text-ink'
                }`}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
          </nav>

          <div className="mt-auto flex flex-col gap-2 border-t border-line pt-4">
            <div className="truncate text-2xs text-ink-muted">{userEmail}</div>
            <button
              onClick={handleLogout}
              className="flex items-center justify-center gap-2 rounded border border-line bg-surface-sunken px-3 py-2 text-xs font-medium text-ink-muted transition-colors hover:bg-surface-raised hover:text-ink"
            >
              <LogOut className="h-4 w-4" />
              Sign out
            </button>
          </div>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">{screen}</main>

      {/* Phone/tablet: thumb-reach tab bar. Safe-area padding clears the home indicator. */}
      <nav className="flex shrink-0 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] lg:hidden">
        {navItems.map((item) => (
          <button
            key={item.id}
            onClick={() => navigate(item.id)}
            className={`flex min-w-0 flex-1 flex-col items-center gap-1 py-2 text-2xs font-medium transition-colors ${
              isActive(item.id) ? 'text-accent' : 'text-ink-muted'
            }`}
          >
            {item.icon}
            <span className="truncate">{item.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
