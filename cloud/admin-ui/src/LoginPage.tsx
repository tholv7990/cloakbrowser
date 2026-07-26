import { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { api } from './api';
import { Button } from './components/Button';

interface LoginPageProps {
  onLogin: (email: string) => void;
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const res = await api.login(email, password);
      sessionStorage.setItem('plasma_admin_token', res.access_token);
      sessionStorage.setItem('plasma_admin_email', res.email);
      onLogin(res.email);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-screen bg-canvas">
      <aside className="hidden flex-1 flex-col justify-between bg-gradient-to-br from-blue-900 to-canvas p-12 lg:flex">
        <div>
          <div className="flex items-center gap-3">
            <svg width="30" height="30" viewBox="0 0 32 32" fill="none">
              <path d="M16 2.5 27 6.2v8.3c0 7.2-4.6 12.9-11 15.5-6.4-2.6-11-8.3-11-15.5V6.2L16 2.5Z"
                    fill="rgb(255 255 255 / .12)" stroke="rgb(255 255 255 / .75)" strokeWidth="1.6"/>
              <path d="M16 9.2c3.4 0 6.2 2.9 6.2 6.4 0 1.4-.4 2.6-1.1 3.7-1.2-2.6-3-4-5.1-4-2.6 0-4.2 1.9-4.2 4.4 0 .5.1 1 .2 1.4A6.4 6.4 0 0 1 9.8 15.6c0-3.5 2.8-6.4 6.2-6.4Z"
                    fill="#fff"/>
            </svg>
            <span className="text-lg font-bold text-white">Plasma</span>
          </div>
        </div>

        <div>
          <h2 className="mb-3 text-3xl font-bold text-white">Licences and accounts,<br />in one place.</h2>
          <p className="text-sm text-ink-muted">
            Issue and revoke keys, free a seat, suspend an account, publish a release — every action recorded.
          </p>
        </div>

        <div className="text-xs text-ink-faint uppercase tracking-wider">
          CLOUD · SUPER-ADMIN · USEPLASMA.APP
        </div>
      </aside>

      <div className="flex flex-1 flex-col items-center justify-start px-6 pt-16 lg:justify-center lg:pt-0">
        <form onSubmit={handleSubmit} className="w-full max-w-xs">
          <div className="mb-8">
            <h1 className="mb-3 text-3xl font-bold leading-tight text-ink">Admin sign in</h1>
            <p className="text-sm leading-relaxed text-ink-muted">Super-admin access. Every action is recorded.</p>
          </div>

          <div className="mb-5">
            <label htmlFor="email" className="mb-2 block text-xs font-semibold uppercase tracking-wide text-ink">Email</label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              placeholder="you@useplasma.app"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input-field"
            />
          </div>

          <div className="mb-6">
            <label htmlFor="password" className="mb-2 block text-xs font-semibold uppercase tracking-wide text-ink">Password</label>
            <div className="relative">
              <input
                id="password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input-field pr-12"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-2 top-1/2 -translate-y-1/2 inline-flex items-center justify-center w-10 h-10 rounded text-ink-muted hover:text-ink hover:bg-surface-raised transition-colors"
                title={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? (
                  <EyeOff className="h-5 w-5" />
                ) : (
                  <Eye className="h-5 w-5" />
                )}
              </button>
            </div>
          </div>

          {error && (
            <div className="mb-6 rounded-lg border border-danger/40 bg-danger/15 px-4 py-3 text-sm font-medium text-danger">
              {error}
            </div>
          )}

          <Button
            type="submit"
            disabled={loading}
            variant="primary"
            className="w-full"
          >
            {loading ? 'Signing in...' : 'Sign in'}
          </Button>
        </form>
      </div>
    </div>
  );
}
