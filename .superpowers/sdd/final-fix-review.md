# Proxy Quality Scanner Final-Fix Review

## Readiness

**READY.** Four controlled live runs now exist and later runs reused the cache. The fourth run verifies the corrected multi-input Turnstile probe with Cloudflare `passed`. No Critical or Important finding remains.

## Critical

None. The final re-review confirmed that malformed urllib causes are suppressed (`benchmarks/proxy_intelligence.py:112-119`), required list files with no valid networks become unavailable (`benchmarks/proxy_intelligence.py:564-587`), and dataset URL/time/hash/size provenance is verified rather than fabricated (`benchmarks/proxy_intelligence.py:509-539`). Focused regressions cover those cases (`tests/test_proxy_intelligence.py:62-71`, `:212-277`).

## Important

None remaining. The live managed widget now distinguishes a persistent in-frame checkbox (`interactive`) from token success (`passed`) and an indeterminate/loading widget (`pending`). Token success has precedence and is true when any matching response input is nonempty, including when an earlier input is empty. Only the boolean predicate result leaves the page. Detection observes only; it does not click, check, press, submit, or retry the challenge.

## Minor finding disposition

- Identity evidence completeness is independent from alignment: five observed dimensions with one DNS mismatch now report `complete: true`, `aligned: false`, and `status: mismatch`.
- README explicitly documents scanner-relay `socks5://` local DNS versus `socks5h://` upstream DNS.
- The design now maps only explicit structured ISP/residential evidence to `residential_or_isp`; a generic backbone ASN remains `unknown`.
- Progress and the final-fix report now include all three live runs, cache reuse, actual-credential JSON scans, structural privacy inspection, and the direct control.

## Live acceptance evidence

Runs `20260721T120143.213678Z`, `20260721T120315.404689Z`, and `20260721T122352.699808Z` all reproduced Google CAPTCHA, captured Cloudflare/Google screenshots, retained AS3257/GTT evidence as `unknown`/`low`, recorded the expected SOCKS5 local-DNS mismatch, and summarized `blocked`/`no`. All three `sources.json` files are byte-identical (SHA-256 `15722f67cbe644bde4ea832d75eefb9c89d7aa3f3451a1c19f4afea4569f246e`) with unchanged retrieval timestamps/checksums, demonstrating that the second and third runs reused the cache. Actual username/password scans across all three reports/manifests returned no matches; structural inspection found no auth headers, cookies, CAPTCHA values, HTML, profile paths, or browser storage, and all six proxy-run PNGs plus the direct-control PNG contained only `IHDR`/`IDAT`/`IEND`. The separate direct control returned ordinary Google results and is explicitly excluded from proxy evidence.

The immutable first and second reports retain pre-fix parser output, and the third exposed the multiple-response-input probe defect. The fourth report `20260721T123856.982677Z` is current-parser evidence: Cloudflare `passed`, Google `captcha`, identity evidence complete with the expected SOCKS5 local-DNS mismatch, and summary `blocked` / unsuitable `no`.

## Verified resolved areas

Credential reconstruction and CLI scrubbing, the loopback-only browser launch, authenticated HTTP/HTTPS/SOCKS5/SOCKS5H relay negotiation and cleanup, tri-state identity evidence and clean gating, classifier types/conflicts/evidence, required-source validation, public summary schema, CLI/direct-control separation, connectivity evidence, reputation semantics, passive Cloudflare state parsing, screenshot sanitization, and documentation match the intended contract. The latest multi-input regression was observed RED (`1 failed`) before the fix. Fresh evidence after the final source edit: focused Turnstile-state GREEN `4 passed`; site suite `28 passed`; complete deterministic scanner/relay suite `139 passed in 9.28s`; core launch/proxy regressions `110 passed in 7.66s`; all five proxy-quality modules compiled successfully.
