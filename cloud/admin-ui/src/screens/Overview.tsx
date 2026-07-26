import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Overview } from '../types';

export function OverviewScreen() {
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.overview().then(d => setData(d as any)).finally(() => setLoading(false));
  }, []);

  const cards = [
    { key: 'users', label: 'Users' },
    { key: 'users_suspended', label: 'Suspended' },
    { key: 'keys', label: 'Licences' },
    { key: 'keys_active', label: 'Active licences' },
    { key: 'redemptions', label: 'Activations' },
    { key: 'keys_expiring_30d', label: 'Expiring in 30d' },
  ];

  if (loading) return <div className="p-6 text-sm text-ink-muted">Loading…</div>;

  return (
    <div className="grid grid-cols-2 gap-3 p-4 sm:gap-4 sm:p-6 lg:grid-cols-3">
      {cards.map(({ key, label }) => (
        <div key={key} className="rounded-lg border border-line bg-surface p-4 sm:p-6">
          <div className="text-2xl font-bold text-ink sm:text-3xl">
            {data?.[key as keyof Overview] ?? 0}
          </div>
          <div className="mt-1 text-xs text-ink-muted">{label}</div>
        </div>
      ))}
    </div>
  );
}
