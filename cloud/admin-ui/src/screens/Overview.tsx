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

  if (loading) return <div className="p-6">Loading…</div>;

  return (
    <div className="grid gap-4 p-6 sm:grid-cols-2 lg:grid-cols-3">
      {cards.map(({ key, label }) => (
        <div key={key} className="rounded-lg border border-gray-700 bg-zinc-900 p-6">
          <div className="text-3xl font-bold text-white">{data?.[key as keyof Overview] ?? 0}</div>
          <div className="text-xs text-gray-400">{label}</div>
        </div>
      ))}
    </div>
  );
}
