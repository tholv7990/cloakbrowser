import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Plan } from '../types';

export function PlansScreen() {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.plans().then(p => setPlans(p as any)).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-6">Loading…</div>;

  return (
    <div className="p-6">
      <div className="overflow-x-auto rounded border border-gray-700">
        <table className="w-full text-sm">
          <thead className="border-b border-gray-700 bg-zinc-800">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Plan</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Name</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Seats</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Profiles</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Sessions</th>
            </tr>
          </thead>
          <tbody>
            {plans.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-4 text-center text-gray-400">No plans</td>
              </tr>
            ) : (
              plans.map((p) => (
                <tr key={p.id} className="border-b border-gray-700 hover:bg-zinc-800">
                  <td className="px-4 py-2 text-white">{p.id}</td>
                  <td className="px-4 py-2 text-gray-300">{p.name}</td>
                  <td className="px-4 py-2 text-gray-300">{p.max_devices}</td>
                  <td className="px-4 py-2 text-gray-300">{p.max_profiles}</td>
                  <td className="px-4 py-2 text-gray-300">{p.max_sessions}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
