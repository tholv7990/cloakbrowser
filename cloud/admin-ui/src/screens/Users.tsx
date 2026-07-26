import { useEffect, useState } from 'react';
import { api } from '../api';
import type { User, UserDetail } from '../types';

export function UsersScreen({ onSelectUser }: { onSelectUser: (id: string) => void }) {
  const [query, setQuery] = useState('');
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);

  async function loadUsers() {
    setLoading(true);
    try {
      const res = await api.users(query || undefined) as any;
      setUsers(res.items);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadUsers();
  }, []);

  async function handleStatusChange(id: string, status: string) {
    const newStatus = status === 'active' ? 'suspended' : 'active';
    if (newStatus === 'suspended' && !confirm('Suspend this account? Their live sessions end immediately.')) return;

    try {
      await api.setUserStatus(id, newStatus);
      loadUsers();
    } catch (err) {
      alert(`Failed to ${newStatus} user: ${err}`);
    }
  }

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="flex gap-2">
        <input
          type="text"
          placeholder="Search email…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && loadUsers()}
          className="flex-1 rounded border border-gray-700 bg-zinc-900 px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
        />
        <button
          onClick={loadUsers}
          disabled={loading}
          className="rounded border border-gray-700 bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-600"
        >
          Search
        </button>
      </div>

      <div className="overflow-x-auto rounded border border-gray-700">
        <table className="w-full text-sm">
          <thead className="border-b border-gray-700 bg-zinc-800">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Email</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Status</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Role</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Joined</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {users.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-4 text-center text-gray-400">No users</td>
              </tr>
            ) : (
              users.map((u) => (
                <tr key={u.id} className="border-b border-gray-700 hover:bg-zinc-800">
                  <td
                    className="cursor-pointer px-4 py-2 text-blue-400 hover:underline"
                    onClick={() => onSelectUser(u.id)}
                  >
                    {u.email}
                  </td>
                  <td className="px-4 py-2">
                    <span className={`rounded px-2 py-1 text-xs font-medium ${
                      u.status === 'active' ? 'bg-green-900/30 text-green-300' : 'bg-red-900/30 text-red-300'
                    }`}>
                      {u.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-300">{u.role}</td>
                  <td className="px-4 py-2 text-gray-400">
                    {new Date(u.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => handleStatusChange(u.id, u.status)}
                      className={`rounded px-3 py-1 text-xs font-medium ${
                        u.status === 'active'
                          ? 'bg-yellow-900/30 text-yellow-300 hover:bg-yellow-900/50'
                          : 'bg-green-900/30 text-green-300 hover:bg-green-900/50'
                      }`}
                    >
                      {u.status === 'active' ? 'Suspend' : 'Restore'}
                    </button>
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
