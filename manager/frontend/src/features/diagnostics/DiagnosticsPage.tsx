import { useState } from 'react';
import { Activity, Chrome, Fingerprint, Play, TriangleAlert } from 'lucide-react';
import type { DiagnosticKind, DiagnosticRun } from '@/types/api';
import { useAppData } from '@/hooks/useAppData';
import { useProfiles } from '@/features/profiles/api';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Select';
import { Badge, type Tone } from '@/components/ui/Badge';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/states';
import { relativeTime } from '@/lib/format';
import { useDiagnostics, useRunDirectGoogleControl, useRunPixelscan } from './api';

const KIND_LABEL: Record<DiagnosticKind, string> = {
  proxy_quality: 'Proxy quality',
  pixelscan: 'Pixelscan',
  direct_google_control: 'Google control',
  launch_failure: 'Launch failure',
  fingerprint_verification: 'Fingerprint check',
};

const STATE_TONE: Record<DiagnosticRun['state'], Tone> = {
  queued: 'neutral',
  running: 'info',
  completed: 'success',
  failed: 'danger',
};

export function DiagnosticsPage() {
  const app = useAppData();
  const diagnostics = useDiagnostics();
  const profiles = useProfiles({ page: 1, page_size: 100, sort: 'name' });
  const directGoogle = useRunDirectGoogleControl();
  const pixelscan = useRunPixelscan();
  const [pixelProfile, setPixelProfile] = useState('');

  const runs = diagnostics.data ?? [];
  const failures = runs.filter((run) => run.kind === 'launch_failure');
  const browser = app.isLoading ? null : app.browser;

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-5 py-6">
      <section className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-line bg-surface p-4">
          <div className="mb-2 flex items-center gap-2 text-ink">
            <Chrome className="h-4 w-4 text-accent" />
            <h2 className="font-display text-[15px] font-semibold">Browser &amp; runtime</h2>
          </div>
          {browser ? (
            <dl className="space-y-1 text-[13px]">
              <div className="flex justify-between">
                <dt className="text-ink-faint">Browser</dt>
                <dd className="text-ink">{browser.name}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-faint">Version</dt>
                <dd className="data text-ink">{browser.version}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-faint">Chromium</dt>
                <dd className="data text-ink">{browser.chromium_version}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-faint">Binary present</dt>
                <dd>
                  {browser.path_present ? (
                    <Badge tone="success">Yes</Badge>
                  ) : (
                    <Badge tone="danger">No</Badge>
                  )}
                </dd>
              </div>
            </dl>
          ) : (
            <LoadingBlock label="Loading…" className="py-6" />
          )}
        </div>

        <div className="space-y-2 rounded-lg border border-line bg-surface p-4">
          <div className="mb-1 flex items-center gap-2 text-ink">
            <Activity className="h-4 w-4 text-accent" />
            <h2 className="font-display text-[15px] font-semibold">Controls</h2>
          </div>
          <Button
            variant="secondary"
            size="sm"
            className="w-full justify-start"
            onClick={() => directGoogle.mutate()}
            loading={directGoogle.isPending}
          >
            <Play className="h-3.5 w-3.5" /> Run direct-network Google control
          </Button>
          <div className="flex gap-2">
            <Select
              className="flex-1"
              value={pixelProfile}
              onChange={(e) => setPixelProfile(e.target.value)}
              placeholder="Choose a profile"
              options={(profiles.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }))}
            />
            <Button
              variant="secondary"
              size="sm"
              onClick={() => pixelProfile && pixelscan.mutate(pixelProfile)}
              loading={pixelscan.isPending}
              disabled={!pixelProfile}
            >
              <Fingerprint className="h-3.5 w-3.5" /> Pixelscan
            </Button>
          </div>
          <p className="text-2xs text-ink-faint">Diagnostics never automate CAPTCHA interaction.</p>
        </div>
      </section>

      {failures.length > 0 && (
        <section>
          <h2 className="mb-2 flex items-center gap-2 font-display text-[15px] font-semibold text-ink">
            <TriangleAlert className="h-4 w-4 text-danger" /> Recent launch failures
          </h2>
          <ul className="space-y-2">
            {failures.map((run) => (
              <li
                key={run.id}
                className="rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-[13px]"
              >
                <div className="flex items-center justify-between">
                  <span className="text-danger">{run.summary}</span>
                  <span className="text-2xs text-ink-faint">{relativeTime(run.created_at)}</span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h2 className="mb-2 font-display text-[15px] font-semibold text-ink">Diagnostic history</h2>
        {diagnostics.isLoading ? (
          <LoadingBlock label="Loading diagnostics…" />
        ) : diagnostics.isError ? (
          <ErrorState
            message={(diagnostics.error as Error).message}
            onRetry={() => diagnostics.refetch()}
          />
        ) : runs.length === 0 ? (
          <EmptyState
            icon={<Activity className="h-5 w-5" />}
            title="No diagnostic runs yet"
            description="Run a control above or a proxy quality test from the Proxies screen."
          />
        ) : (
          <ul className="divide-y divide-line rounded-lg border border-line">
            {runs.map((run) => (
              <li key={run.id} className="flex items-start justify-between gap-4 px-3 py-2.5">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Badge tone="neutral">{KIND_LABEL[run.kind]}</Badge>
                    <Badge tone={STATE_TONE[run.state]}>{run.state}</Badge>
                  </div>
                  <p className="mt-1 text-[13px] text-ink-muted">{run.summary}</p>
                  {run.artifact_path && (
                    <p className="data mt-0.5 truncate text-2xs text-ink-faint">
                      {run.artifact_path}
                    </p>
                  )}
                </div>
                <span className="shrink-0 text-2xs text-ink-faint">
                  {relativeTime(run.created_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
