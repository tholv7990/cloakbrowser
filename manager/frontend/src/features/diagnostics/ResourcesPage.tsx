import { ResourceMonitor } from './ResourceMonitor';

/** Live runtime resource monitor. Its own screen (gated by `browser_runtime`)
 * rather than a Diagnostics panel, since it is about running profiles, not
 * fingerprint diagnostics. */
export function ResourcesPage() {
  return (
    <div className="mx-auto max-w-4xl px-5 py-6">
      <ResourceMonitor />
    </div>
  );
}
