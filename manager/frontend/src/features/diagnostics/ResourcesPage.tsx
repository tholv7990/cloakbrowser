import { ResourceMonitor } from './ResourceMonitor';
import { SessionHistory } from './SessionHistory';

/** Live runtime resource monitor + recent session history. Its own screen
 * (gated by `browser_runtime`) rather than a Diagnostics panel, since it is
 * about running profiles, not fingerprint diagnostics. */
export function ResourcesPage() {
  // The app shell's <main> is overflow-hidden, so each page owns its scroll.
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-5 px-5 py-6">
        <ResourceMonitor />
        <SessionHistory />
      </div>
    </div>
  );
}
