import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Release } from '../types';

export function ReleasesScreen() {
  const [channel, setChannel] = useState('stable');
  const [version, setVersion] = useState('');
  const [minVersion, setMinVersion] = useState('');
  const [artifactUrl, setArtifactUrl] = useState('');
  const [sha256, setSha256] = useState('');
  const [signature, setSignature] = useState('');
  const [releases, setReleases] = useState<Release[]>([]);
  const [loading, setLoading] = useState(false);

  async function loadReleases() {
    try {
      const result = await api.releases();
      setReleases((result as any) || []);
    } catch (err) {
      alert(`Failed to load releases: ${err}`);
    }
  }

  useEffect(() => {
    loadReleases();
  }, []);

  async function handlePublish() {
    const msg = `Publish ${version} to ${channel}? Every client on that channel will be offered it, and it cannot be republished.`;
    if (!confirm(msg)) return;

    setLoading(true);
    try {
      await api.publishRelease({
        channel,
        version,
        min_supported_version: minVersion,
        artifact_url: artifactUrl,
        sha256,
        signature,
      });
      setVersion('');
      setMinVersion('');
      setArtifactUrl('');
      setSha256('');
      setSignature('');
      loadReleases();
    } catch (err) {
      alert(`Failed to publish: ${err}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-col gap-4 rounded-lg border border-gray-700 bg-zinc-900 p-4">
        <div className="flex flex-wrap gap-2">
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
            className="rounded border border-gray-700 bg-zinc-800 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
          >
            <option>stable</option>
            <option>beta</option>
          </select>
          <input
            type="text"
            placeholder="Version (1.2.0)"
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            className="w-40 rounded border border-gray-700 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
          />
          <input
            type="text"
            placeholder="Min supported"
            value={minVersion}
            onChange={(e) => setMinVersion(e.target.value)}
            className="w-40 rounded border border-gray-700 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
          />
          <button
            onClick={handlePublish}
            disabled={loading}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-600"
          >
            Publish
          </button>
        </div>

        <div className="flex flex-wrap gap-2">
          <input
            type="text"
            placeholder="Artifact URL"
            value={artifactUrl}
            onChange={(e) => setArtifactUrl(e.target.value)}
            className="flex-1 rounded border border-gray-700 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
            style={{ minWidth: '260px' }}
          />
          <input
            type="text"
            placeholder="SHA-256 (64 hex)"
            value={sha256}
            onChange={(e) => setSha256(e.target.value)}
            className="flex-1 rounded border border-gray-700 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
            style={{ minWidth: '220px' }}
          />
          <input
            type="text"
            placeholder="Signature"
            value={signature}
            onChange={(e) => setSignature(e.target.value)}
            className="flex-1 rounded border border-gray-700 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
            style={{ minWidth: '200px' }}
          />
        </div>
      </div>

      <div className="overflow-x-auto rounded border border-gray-700">
        <table className="w-full text-sm">
          <thead className="border-b border-gray-700 bg-zinc-800">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Channel</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Version</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Min supported</th>
              <th className="px-4 py-2 text-left font-medium text-gray-300">Published</th>
            </tr>
          </thead>
          <tbody>
            {releases.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-4 text-center text-gray-400">Nothing published</td>
              </tr>
            ) : (
              releases.map((r, i) => (
                <tr key={i} className="border-b border-gray-700 hover:bg-zinc-800">
                  <td className="px-4 py-2">
                    <span className="rounded bg-blue-900/30 px-2 py-1 text-xs font-medium text-blue-300">
                      {r.channel}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-300">{r.version}</td>
                  <td className="px-4 py-2 text-gray-300">{r.min_supported_version}</td>
                  <td className="px-4 py-2 text-gray-400">
                    {new Date(r.published_at).toLocaleString()}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-gray-500">
        Published releases are immutable - every client on the channel is offered this build, so a version is never republished.
      </p>
    </div>
  );
}
