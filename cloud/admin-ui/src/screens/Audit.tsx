import { useEffect, useState } from 'react';
import { api } from '../api';
import type { AuditEvent } from '../types';

export function AuditScreen() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.audit().then(e => setEvents(e as any)).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-6">Loading…</div>;

  return (
    <div className="p-6">
      <div className="overflow-x-auto rounded border border-gray-700">
        <table className="w-full text-sm">
          <thead className="border-b border-gray-700 bg-zinc-800">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-gray-300">When</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Actor</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Action</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Subject</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Detail</th>
            </tr>
          </thead>
          <tbody>
            {events.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-4 text-center text-gray-400">Nothing recorded yet</td>
              </tr>
            ) : (
              events.map((e, i) => (
                <tr key={i} className="border-b border-gray-700 hover:bg-zinc-800">
                  <td className="px-4 py-2 text-gray-400">
                    {new Date(e.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-gray-300">{e.actor}</td>
                  <td className="px-4 py-2 text-gray-300">{e.action}</td>
                  <td className="px-4 py-2 text-gray-400">
                    {e.subject_type}/{e.subject_id.slice(0, 8)}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-gray-400">
                    {JSON.stringify(e.data)}
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
