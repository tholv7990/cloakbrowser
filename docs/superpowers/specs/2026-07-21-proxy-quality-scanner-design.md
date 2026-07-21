# Proxy Quality Scanner Design

## Objective

Add a standalone, repeatable CLI that evaluates a supplied proxy without exposing credentials. The scanner reports network type and reputation as separate dimensions, incorporates trusted open-source intelligence, and uses a small number of browser checks to measure real-site outcomes.

The scanner must not describe an IP as universally clean. Its verdict represents the observed data sources and sites at the scan time.

## Interface

Run the scanner as:

```powershell
$env:CLOAK_TEST_PROXY = "socks5://user:password@host:port"
python -m benchmarks.proxy_quality --output-dir benchmarks/results/proxy-quality
```

Run the required direct-network Google control separately, with no proxy input:

```powershell
Remove-Item Env:CLOAK_TEST_PROXY -ErrorAction SilentlyContinue
python -m benchmarks.proxy_quality --direct-control --output-dir benchmarks/results/proxy-quality
```

The control writes under `direct-control/<timestamp>/` and is explicitly excluded from proxy report evidence.

Optional environment variables:

- `IPINFO_TOKEN`: enables IPinfo enrichment when available.
- `PROXY_QUALITY_SKIP_BROWSER=1`: performs network and intelligence checks without Google, Cloudflare, or WebRTC browser checks.

The proxy is accepted only through `CLOAK_TEST_PROXY`. It is never accepted as a command-line argument because command lines can be recorded in shell history and process listings.

For browser-enabled proxy scans, a scoped HTTP relay binds to an ephemeral `127.0.0.1` port. Chromium receives only that credential-free loopback endpoint; the parent process authenticates the relay to HTTP, HTTPS, SOCKS5, or SOCKS5H upstreams and closes the relay after the browser context.

## Trusted upstream sources

The implementation will reuse or consume data from established, active projects rather than duplicating their databases:

- `ipinfo/cli`: official Apache-2.0 IPinfo client, used as optional enrichment for ASN type, hosting, mobile, and privacy indicators.
- `sapics/ip-location-db`: daily ASN and geolocation data used for local/no-token classification.
- `stamparm/ipsum`: daily aggregated malicious-IP reputation list.
- `firehol/blocklist-ipsets`: curated aggregation of abuse, proxy, and threat lists.

Every upstream integration is isolated behind an adapter. Downloaded datasets are cached with source URL, retrieval time, and checksum. A source failure produces an `unavailable` signal rather than silently changing a verdict.

No CAPTCHA-solving or challenge-bypass package is included.

## Scan stages

### 1. Proxy connectivity

- Parse HTTP, HTTPS, SOCKS5, and SOCKS5H URLs using the existing CloakBrowser proxy conventions.
- Resolve the exit IP through two independent echo services.
- Record connection success, median latency from three lightweight requests, exit-IP agreement, and country consistency.
- Redact username and password before logging or serializing any proxy value.

### 2. Network classification

Return one of:

- `mobile`
- `residential_or_isp`
- `datacenter_or_hosting`
- `unknown`

Classification evidence includes ASN, ASN organization, ASN category, carrier/MCC/MNC when available, and hosting/mobile/privacy flags. Provider marketing labels are not trusted as evidence.

Confidence rules:

- `high`: two independent structured signals agree, such as a mobile carrier record plus `is_mobile`, or hosting ASN type plus a hosting flag.
- `medium`: one structured source classifies the network and no source conflicts.
- `low`: classification relies on ASN organization heuristics or sources conflict.

Structured provider or ASN-category evidence that explicitly identifies `isp` or `residential` maps to `residential_or_isp`, because those two access-network cases cannot be separated reliably from that evidence alone. A generic ASN/range record with no structured network category remains `unknown`; backbone/transit organization names such as AS3257 are not inferred to be residential, ISP, or hosting from the name alone.

### 3. Reputation intelligence

- Check exact IP and matching CIDR entries against IPsum and a conservative subset of FireHOL lists.
- Record source name, list category, and match granularity.
- Do not combine all FireHOL lists indiscriminately; broad scanner and country lists would create misleading false positives.
- Treat absence from lists as `no_listed_abuse`, not proof that the IP is clean.

### 4. Leak and identity alignment

Launch a dedicated CloakBrowser persistent profile with:

- `fingerprint_preset="consistent"`
- a fixed test seed
- `geoip=True`
- the supplied proxy

Compare HTTP exit IP, WebRTC-visible IP, timezone, locale, and DNS behavior. Report mismatches independently because a clean IP with a WebRTC or DNS leak is not a usable proxy profile.

### 5. Safe live-site checks

Browser checks make at most one initial request per site per scan:

- Cloudflare Turnstile managed demo: record widget availability, automatic token generation, interactive challenge, or error. Do not click or solve an interactive challenge.
- Google Search: issue one benign fixed query and record normal results, consent page, `/sorry/` redirect, unusual-traffic page, or CAPTCHA. Do not interact with reCAPTCHA.
- Pixelscan remains a separate deeper fingerprint scanner and is linked from the report rather than run automatically.

The scanner must avoid retries that could worsen IP reputation. Network errors are recorded rather than retried against protected sites.

## Verdict model

The JSON report contains independent sections for:

- `connectivity`
- `classification`
- `reputation_intelligence`
- `identity_alignment`
- `site_outcomes`
- `summary`

Summary values:

- `type`: classification enum above.
- `type_confidence`: `high`, `medium`, or `low`.
- `reputation`: `clean_observed`, `questionable`, `blocked`, or `unknown`.
- `suitable_for_protected_sites`: `yes`, `no`, or `uncertain`.

Summary rules:

- `blocked`: Google or Cloudflare returns an explicit block/CAPTCHA, or a high-confidence abuse list matches.
- `questionable`: lower-confidence list matches, inconsistent exit IP, or identity leaks exist.
- `clean_observed`: connectivity succeeds, no selected list matches, identity signals align, Cloudflare passes without interaction, and Google returns results normally.
- `unknown`: required checks are unavailable or skipped, preventing a supported conclusion.

`clean_observed` always includes the scan timestamp and tested sites. It must never be presented as a permanent or universal property.

## Artifacts and privacy

Each scan creates a timestamped directory containing:

- `report.json`
- `cloudflare.png` when the browser stage runs
- `google.png` when the browser stage runs
- a source manifest with dataset checksums and retrieval dates

PNG structure is validated and nonessential metadata is stripped before finalization. The separate direct control uses `direct-control/<timestamp>/direct-control.json` and `google.png`, not the proxy timestamp directory.

Artifacts may contain the public exit IP because it is the subject being evaluated. They must never contain proxy usernames, passwords, authentication headers, cookies, CAPTCHA tokens, or complete browser storage state.

Console output shows a compact summary and a redacted endpoint. JSON stores the same redacted endpoint.

## Error handling and exit codes

- `0`: scan completed; verdict may be any value and callers should read JSON.
- `2`: invalid configuration or proxy URL.
- `3`: proxy connectivity failed before an exit IP could be established.
- `4`: report could not be written safely.

An IP receiving a bad reputation verdict is a valid scan result, not a process error.

## Testing

Unit tests cover:

- Proxy redaction and validation.
- CIDR membership and list parsing.
- Classification evidence and confidence rules.
- Reputation aggregation and summary rules.
- Google and Cloudflare page-state parsing using stored sanitized fixtures.
- Source failure and partial-result behavior.
- Credential absence from serialized reports.

Integration tests use local HTTP/SOCKS fixtures where practical. Live tests are opt-in because they consume proxy bandwidth and site reputation budget. A live test must never solve a CAPTCHA.

## Documentation

The README will explain:

- The difference between proxy type and reputation.
- Why residential or mobile does not imply clean.
- Why datacenter does not automatically imply blocked.
- How confidence is calculated.
- How to run no-browser and full scans.
- Dataset licenses and attribution requirements.

## Success criteria

- Credentials appear nowhere in source, console output, JSON, screenshots metadata, or failure messages.
- The current known proxy is classified with evidence and reproduces its Google CAPTCHA outcome.
- The direct-network control produces normal Google results without affecting the proxy report.
- Classification uncertainty is explicit; no heuristic-only result receives high confidence.
- Re-running the scanner uses cached intelligence datasets and sends at most one request to each protected-site check.
- All deterministic unit tests pass without network access.

## Workspace limitation

This workspace is not a Git repository, so the specification cannot be committed. Implementation changes will remain directly in the shared workspace.
