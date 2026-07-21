import { Check, CircleAlert, TriangleAlert, X } from 'lucide-react';
import type { AlignmentFinding, ProxyQualityReport, ProxyQuickTest } from '@/types/api';
import { Badge, type Tone } from '@/components/ui/Badge';
import { formatLatency, formatPercent } from '@/lib/format';
import { cn } from '@/lib/cn';

function KeyVal({
  label,
  value,
  mono,
}: {
  label: string;
  value: string | null | undefined;
  mono?: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-2xs uppercase tracking-wide text-ink-faint">{label}</dt>
      <dd className={cn('text-[13px] text-ink', mono && 'data')}>{value || '—'}</dd>
    </div>
  );
}

export function ProxyQuickResult({ result }: { result: ProxyQuickTest }) {
  return (
    <div className="space-y-3 rounded-lg border border-line bg-surface-sunken p-3">
      <div className="flex items-center gap-2">
        {result.ok ? (
          <Badge tone="success">
            <Check className="h-3 w-3" /> Reachable
          </Badge>
        ) : (
          <Badge tone="danger">
            <X className="h-3 w-3" /> Unreachable
          </Badge>
        )}
        {result.exit_ip_matches != null && (
          <Badge tone={result.exit_ip_matches ? 'success' : 'warning'}>
            {result.exit_ip_matches ? 'Exit IP agrees' : 'Exit IP mismatch'}
          </Badge>
        )}
        <span className="ml-auto text-2xs text-ink-faint">
          Median {formatLatency(result.latency_ms)}
        </span>
      </div>
      {result.error && <p className="text-2xs text-danger">{result.error}</p>}
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <KeyVal label="Exit IP" value={result.exit_ip} mono />
        <KeyVal label="Country" value={result.country} />
        <KeyVal label="City" value={result.city} />
        <KeyVal label="Timezone" value={result.timezone} mono />
        <KeyVal label="ASN" value={result.asn} mono />
        <KeyVal label="Organization" value={result.organization} />
      </dl>
    </div>
  );
}

const ALIGNMENT_TONE: Record<AlignmentFinding['status'], Tone> = {
  aligned: 'success',
  mismatch: 'warning',
  leak: 'danger',
  unknown: 'neutral',
};

// Static classes so Tailwind keeps them (no dynamic `text-${tone}`).
const ALIGNMENT_ICON_CLASS: Record<AlignmentFinding['status'], string> = {
  aligned: 'text-success',
  mismatch: 'text-warning',
  leak: 'text-danger',
  unknown: 'text-ink-faint',
};

function AlignmentRow({ label, finding }: { label: string; finding: AlignmentFinding }) {
  const Icon =
    finding.status === 'aligned' ? Check : finding.status === 'leak' ? TriangleAlert : CircleAlert;
  const tone = ALIGNMENT_TONE[finding.status];
  return (
    <div className="flex items-start gap-2.5 py-1.5">
      <span className={cn('mt-0.5', ALIGNMENT_ICON_CLASS[finding.status])}>
        <Icon className="h-3.5 w-3.5" />
      </span>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-medium text-ink">{label}</span>
          <Badge tone={tone}>{finding.status}</Badge>
        </div>
        <p className="text-2xs text-ink-muted">{finding.detail}</p>
      </div>
    </div>
  );
}

const OUTCOME_TONE: Record<string, Tone> = {
  passed: 'success',
  captcha: 'warning',
  challenge: 'warning',
  blocked: 'danger',
  failed: 'danger',
  unknown: 'neutral',
};

export function ProxyQualityReportView({ report }: { report: ProxyQualityReport }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {report.proxy_type && (
          <Badge tone="info">
            {report.proxy_type} · {formatPercent(report.type_confidence)} confidence
          </Badge>
        )}
        {report.reputation && (
          <Badge
            tone={
              report.reputation === 'clean'
                ? 'success'
                : report.reputation === 'malicious'
                  ? 'danger'
                  : 'warning'
            }
          >
            Reputation: {report.reputation}
          </Badge>
        )}
        {report.google_outcome && (
          <Badge tone={OUTCOME_TONE[report.google_outcome]}>Google: {report.google_outcome}</Badge>
        )}
        {report.turnstile_outcome && (
          <Badge tone={OUTCOME_TONE[report.turnstile_outcome]}>
            Turnstile: {report.turnstile_outcome}
          </Badge>
        )}
        <span className="ml-auto text-2xs text-ink-faint">
          Median {formatLatency(report.latency_ms)}
        </span>
      </div>

      {report.matched_lists.length > 0 && (
        <p className="text-2xs text-warning">Matched lists: {report.matched_lists.join(', ')}</p>
      )}

      <dl className="grid grid-cols-2 gap-3 rounded-lg border border-line bg-surface-sunken p-3 sm:grid-cols-3">
        <KeyVal label="Exit IP" value={report.exit_ip} mono />
        <KeyVal label="Country" value={report.country} />
        <KeyVal label="City" value={report.city} />
        <KeyVal label="Timezone" value={report.timezone} mono />
        <KeyVal label="ASN" value={report.asn} mono />
        <KeyVal label="Organization" value={report.organization} />
      </dl>

      <div className="rounded-lg border border-line p-3">
        <p className="mb-1 text-2xs font-semibold uppercase tracking-wide text-ink-faint">
          Alignment
        </p>
        <div className="divide-y divide-line">
          <AlignmentRow label="HTTP headers" finding={report.alignment.http} />
          <AlignmentRow label="WebRTC" finding={report.alignment.webrtc} />
          <AlignmentRow label="DNS" finding={report.alignment.dns} />
          <AlignmentRow label="Timezone" finding={report.alignment.timezone} />
          <AlignmentRow label="Locale" finding={report.alignment.locale} />
        </div>
      </div>

      {(report.screenshot_path || report.report_path) && (
        <div className="space-y-1 text-2xs text-ink-muted">
          {report.screenshot_path && (
            <p className="data truncate">Screenshot: {report.screenshot_path}</p>
          )}
          {report.report_path && <p className="data truncate">Report: {report.report_path}</p>}
        </div>
      )}

      <p className="text-2xs text-ink-faint">
        {report.observed_scope} Checked {new Date(report.checked_at).toLocaleString()}.
      </p>
    </div>
  );
}
