import { useEffect, useState } from 'react';
import { api } from '../api';
import type { UserDetail } from '../types';

interface UserDetailProps {
  userId: string;
  onBack: () => void;
}

export function UserDetailScreen({ userId, onBack }: UserDetailProps) {
  const [data, setData] = useState<UserDetail | null>(null);
  const [loading, setLoading] = useState(true);

  async function loadUser() {
    try {
      const res = await api.userDetail(userId);
      setData(res as any);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadUser();
  }, [userId]);

  async function handleReleaseDevice(id: string) {
    if (!confirm('Release this device? It frees the seat and the machine must activate again.')) return;

    try {
      await api.releaseDevice(id);
      loadUser();
    } catch (err) {
      alert(`Failed to release device: ${err}`);
    }
  }

  if (loading) return <div className="p-6">Loading…</div>;
  if (!data) return <div className="p-6">User not found</div>;

  const active = data.devices.filter((x) => !x.revoked_at);
  const seatsLabel = data.plan
    ? `${active.length} / ${data.plan.max_devices} seats · ${data.plan.name}`
    : `${active.length} seat${active.length === 1 ? '' : 's'} in use`;

  return (
    <div className="flex flex-col gap-6 p-6">
      <button
        onClick={onBack}
        className="w-fit rounded border border-gray-700 bg-zinc-900 px-3 py-2 text-sm text-gray-300 hover:bg-zinc-800"
      >
        ← Users
      </button>

      <div className="flex items-center justify-between rounded-lg border border-gray-700 bg-zinc-900 p-4">
        <div>
          <h2 className="text-lg font-bold text-white">{data.user.email}</h2>
          <div className="mt-2 flex gap-2">
            <span className={`rounded px-2 py-1 text-xs font-medium ${
              data.user.status === 'active' ? 'bg-green-900/30 text-green-300' : 'bg-red-900/30 text-red-300'
            }`}>
              {data.user.status}
            </span>
            <span className="rounded bg-blue-900/30 px-2 py-1 text-xs font-medium text-blue-300">
              {seatsLabel}
            </span>
          </div>
        </div>
      </div>

      <div>
        <h3 className="mb-3 font-bold text-white">Devices ({data.devices.length})</h3>
        <div className="overflow-x-auto rounded border border-gray-700">
          <table className="w-full text-sm">
            <thead className="border-b border-gray-700 bg-zinc-800">
              <tr>
                <th className="px-4 py-2 text-left font-medium text-gray-300">Device</th>
                <th className="px-4 py-2 text-left font-medium text-gray-300">Platform</th>
                <th className="px-4 py-2 text-left font-medium text-gray-300">Last seen</th>
                <th className="px-4 py-2 text-left font-medium text-gray-300">State</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {data.devices.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-4 text-center text-gray-400">No devices registered</td>
                </tr>
              ) : (
                data.devices.map((dev) => {
                  const isActive = !dev.revoked_at;
                  return (
                    <tr key={dev.id} className="border-b border-gray-700 hover:bg-zinc-800">
                      <td className="px-4 py-2 text-white">{dev.name}</td>
                      <td className="px-4 py-2 text-gray-400">{dev.platform}</td>
                      <td className="px-4 py-2 text-gray-400">
                        {dev.last_seen_at ? new Date(dev.last_seen_at).toLocaleString() : '—'}
                      </td>
                      <td className="px-4 py-2">
                        <span className={`rounded px-2 py-1 text-xs font-medium ${
                          isActive ? 'bg-green-900/30 text-green-300' : 'bg-red-900/30 text-red-300'
                        }`}>
                          {isActive ? 'active' : 'released'}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right">
                        {isActive && (
                          <button
                            onClick={() => handleReleaseDevice(dev.id)}
                            className="rounded bg-yellow-900/30 px-3 py-1 text-xs font-medium text-yellow-300 hover:bg-yellow-900/50"
                          >
                            Release
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <p className="mt-3 text-xs text-gray-500">
          Releasing a device frees its seat immediately. Use this when someone reinstalled Windows and cannot activate.
        </p>
      </div>
    </div>
  );
}
