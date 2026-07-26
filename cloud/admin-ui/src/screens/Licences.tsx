import { useEffect, useState } from 'react';
import { api } from '../api';
import type { ActivationKey } from '../types';

export function LicencesScreen() {
  const [planId, setPlanId] = useState('');
  const [count, setCount] = useState(1);
  const [keyPrefix, setKeyPrefix] = useState('');
  const [keys, setKeys] = useState<ActivationKey[]>([]);
  const [issued, setIssued] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  async function handleIssueKeys() {
    if (!planId.trim()) {
      alert('Enter a plan id');
      return;
    }

    setLoading(true);
    try {
      const result = await api.issueKeys(planId.trim(), count);
      setIssued(result.map((item) => item.key));
      setPlanId('');
      setCount(1);
      await loadKeys();
    } catch (err) {
      alert(`Failed to issue keys: ${err}`);
    } finally {
      setLoading(false);
    }
  }

  async function loadKeys() {
    try {
      const result = await api.lookupKeys(keyPrefix || undefined);
      setKeys((result as any) || []);
    } catch (err) {
      alert(`Failed to lookup keys: ${err}`);
    }
  }

  useEffect(() => {
    loadKeys();
  }, []);

  async function handleRevokeKey(id: string) {
    if (!confirm('Revoke this licence? It cannot be used again.')) return;

    try {
      await api.revokeKey(id);
      loadKeys();
    } catch (err) {
      alert(`Failed to revoke key: ${err}`);
    }
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-col gap-4 rounded-lg border border-gray-700 bg-zinc-900 p-4">
        <div className="flex flex-wrap gap-2">
          <input
            type="text"
            placeholder="Plan id (e.g. pro)"
            value={planId}
            onChange={(e) => setPlanId(e.target.value)}
            className="rounded border border-gray-700 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
          />
          <input
            type="number"
            min="1"
            max="500"
            value={count}
            onChange={(e) => setCount(Math.max(1, Math.min(500, Number(e.target.value))))}
            className="w-24 rounded border border-gray-700 bg-zinc-800 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
          />
          <button
            onClick={handleIssueKeys}
            disabled={loading}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-600"
          >
            Issue licences
          </button>
          <div className="flex-1" />
          <input
            type="text"
            placeholder="Key prefix…"
            value={keyPrefix}
            onChange={(e) => setKeyPrefix(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && loadKeys()}
            className="rounded border border-gray-700 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
          />
          <button
            onClick={loadKeys}
            className="rounded border border-gray-700 bg-zinc-900 px-4 py-2 text-sm font-medium text-gray-300 hover:bg-zinc-800"
          >
            Look up
          </button>
        </div>

        {issued.length > 0 && (
          <div className="rounded bg-yellow-900/20 p-3">
            <div className="mb-2 text-xs font-medium text-yellow-300">Copy these now — they cannot be shown again.</div>
            <div className="space-y-1 rounded bg-black/50 p-2 font-mono text-xs text-gray-300">
              {issued.map((key, i) => (
                <div key={i}>{key}</div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="overflow-x-auto rounded border border-gray-700">
        <table className="w-full text-sm">
          <thead className="border-b border-gray-700 bg-zinc-800">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Key id</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Plan</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Status</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Uses left</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Expires</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {keys.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-4 text-center text-gray-400">No licences</td>
              </tr>
            ) : (
              keys.map((k) => (
                <tr key={k.id} className="border-b border-gray-700 hover:bg-zinc-800">
                  <td className="px-4 py-2 font-mono text-sm text-gray-300">{k.id}</td>
                  <td className="px-4 py-2 text-gray-300">{k.plan_id}</td>
                  <td className="px-4 py-2">
                    <span className={`rounded px-2 py-1 text-xs font-medium ${
                      k.status === 'active' ? 'bg-green-900/30 text-green-300' : 'bg-red-900/30 text-red-300'
                    }`}>
                      {k.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-300">{k.uses_remaining}</td>
                  <td className="px-4 py-2 text-gray-400">
                    {k.expires_at ? new Date(k.expires_at).toLocaleString() : '—'}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {k.status !== 'revoked' && (
                      <button
                        onClick={() => handleRevokeKey(k.id)}
                        className="rounded bg-yellow-900/30 px-3 py-1 text-xs font-medium text-yellow-300 hover:bg-yellow-900/50"
                      >
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
