# Proxy Quality Scanner Final-Fix Report

## Status

**READY.** All Critical/Important findings are corrected. Four controlled live runs were completed and later runs reused the cache. The fourth run (`20260721T123856.982677Z`) is current-parser evidence: Cloudflare `passed`, Google `captcha`, complete identity evidence with the expected SOCKS5 local-DNS mismatch, and summary `blocked` / unsuitable `no`. Actual-credential JSON scans, structural artifact inspection, and a separate direct-network control also passed.

## Final-review finding disposition

| Finding | Disposition and evidence |
|---|---|
| C1: credential parsing/redaction/runtime exposure | Fixed. Strict URL validation rejects suffixes and malformed authorities; redaction reconstructs only scheme/host/port using the last authority delimiter; raw/encoded delimiters and IPv6 are covered. Validation suppresses credential-bearing `urllib` causes. Browser launch receives only an ephemeral `http://127.0.0.1:<port>` relay URL. The private relay keeps HTTP/HTTPS Basic or SOCKS5/SOCKS5H RFC 1929 authentication in the scanner process and has offline socket/lifecycle tests. PNGs are validated, metadata-stripped, secret-checked, and deleted if rejected. |
| C2: vacuous identity alignment | Fixed. The browser stage records source-attributed HTTP exit IP, WebRTC candidates, timezone, locale, and relay DNS delegation. Alignment is tri-state; missing evidence is `unknown`, any mismatch is `questionable`, and all five dimensions must match before `clean_observed`. |
| C3: unavailable sources supporting clean | Fixed. Required IPsum/FireHOL status is propagated into the report and summary gate. Empty/HTML-only datasets are unavailable. Dataset URL, retrieval time, hash, and byte count must exist and match the cache file; provenance is never fabricated. |
| C4: incomplete classifier/evidence | Fixed. Types are `mobile`, `residential_or_isp`, `datacenter_or_hosting`, and `unknown`. Sanitized source/ASN/organization/category/flag evidence is retained. Generic AS3257-like backbone evidence can remain `unknown` rather than being mislabeled. |
| I5: conflicts with high confidence | Fixed. Any cross-category conflict forces `low`; heuristic-only classification is also `low`. |
| I6: summary schema mismatch | Fixed. Summary contains `type`, `type_confidence`, `reputation`, and `suitable_for_protected_sites`; the uncertain value is `uncertain`. Clean results add timestamped observation scope. |
| I7: missing `--output-dir` | Fixed. The CLI accepts only nonsecret `--output-dir PATH` and optional `--direct-control`; proxy input remains environment-only and unsupported arguments are not echoed. |
| I8: incomplete connectivity | Fixed. All three attempts retain endpoint/status evidence, both IPify and AWS must succeed, successful latency median and IP agreement are reported, and geography is explicitly `unavailable`. |
| I9: incomplete reputation semantics | Fixed. Matches retain list source, category, network, and `exact_ip`/`cidr` granularity. Required availability and `no_listed_abuse`/`unavailable` observations remain explicit. |
| I10: Cloudflare state handling | Fixed. Safe URL, HTTP status, and body indicators can produce `blocked`. A managed Turnstile checkbox inside its challenge frame is now `interactive` after polling; a generic/loading frame remains `pending`, and any nonempty matching response input makes the widget `passed` with success precedence. The multi-input token probe evaluates an in-page predicate and returns only a boolean, never token content. Detection is passive and never clicks the widget. |
| I11: incomplete acceptance artifacts | Fixed. Four controlled live runs contain reports, manifests, and both screenshots; later runs reused the cache, and the direct-network control remains separate. The fourth run verifies corrected Cloudflare token parsing. |
| I12: overstated offline docs | Fixed. README and functionality docs state that browser-skip mode still makes proxy connectivity requests and may refresh datasets, and document all confidence/verdict rules and caveats. |

## Additional audit corrections

- Added a traceback-level regression for NFKC-invalid credentialed authorities; the parser now raises its scrubbed error `from None`.
- Rejected required-source files that contain zero valid networks and rejected missing, mismatched, or wrong-source cache provenance.
- Deleted a screenshot when validation/secret inspection rejects it, preventing unsafe partial evidence from remaining in the artifact directory.
- Corrected identity `complete` to mean every dimension was observed (`matches is not None`), independently from whether all dimensions align.
- Added a sanitized managed-Turnstile fixture and passive iframe-checkbox detection. The live top-level "Waiting for verification" text is deliberately not interaction evidence because it appears in both successful and checkbox screenshots.
- Corrected the Turnstile token probe after the third live success screenshot exposed multiple matching response inputs. Playwright's strict `input_value()` call could throw, while choosing only the first input could miss a later populated value. The implementation now tests whether any matching input is nonempty with `evaluate_all()` and serializes only the resulting boolean out of the page.
- Updated the specification, implementation plan, README, functionality map, and this progress ledger to match the implemented contract.

## TDD evidence

Every production correction was preceded by a focused failing test. Representative RED/GREEN evidence recorded during the pass:

- Models/redaction/schema: `16 failed, 7 passed` before implementation; the model suite later passed with the expanded cases.
- Connectivity/reputation/source semantics: `11 failed, 24 passed` before implementation; focused availability and attempt-outcome regressions then passed. The final intelligence suite passed `39` tests.
- Browser identity/site handling: initial import/behavior failures, then focused identity/DNS/direct-control cases passed.
- CLI/artifacts: `9 failed, 15 passed` before orchestration changes; metadata and incomplete/rejected screenshot regressions were separately observed failing and then passing.
- Relay: initial `ModuleNotFoundError`, then `15 passed` across HTTP/HTTPS/SOCKS5/SOCKS5H socket and cleanup tests.
- Final audit regressions: NFKC traceback leak failed then passed; invalid provenance and zero-record datasets failed `2` tests then passed `2`; rejected screenshot retention failed then passed.
- Final live-review regressions: managed checkbox, successful token with a generic frame, pending indeterminate widget, and mismatch completeness produced `3 failed`; a frame-checkbox-sufficiency case then failed independently. After the third live run, the regression with two response inputs (first empty, second populated), no success body text, and a generic frame failed `1` test before the multi-input fix. Focused token/state GREEN passed `4`, and the complete site suite passed `28`.

## Fresh verification

Run after the final source and test edits on 2026-07-21:

```text
python -m pytest tests/test_proxy_quality_models.py tests/test_proxy_intelligence.py tests/test_proxy_auth_relay.py tests/test_proxy_site_checks.py tests/test_proxy_quality_cli.py tests/test_fingerprint_scanners.py -q
139 passed in 9.28s

python -m pytest tests/test_fingerprint_preset.py tests/test_session.py tests/test_launch.py tests/test_persistent_context.py tests/test_proxy.py -q
110 passed in 7.66s

python -m py_compile benchmarks/proxy_quality_models.py benchmarks/proxy_intelligence.py benchmarks/proxy_auth_relay.py benchmarks/proxy_site_checks.py benchmarks/proxy_quality.py
exit 0
```

The direct-network control ran separately and returned Google `results` with a captured screenshot:

```text
benchmarks/results/proxy-quality/direct-control/20260721T114613.017748Z/direct-control.json
```

The JSON records `excluded_from_proxy_report: true`. Visual inspection showed a normal Google results page. PNG structure inspection found only `IHDR`, `IDAT`, and `IEND` chunks.

## Controlled live evidence

Four controlled live runs form a chronological, immutable audit trail:

- `benchmarks/results/proxy-quality/20260721T120143.213678Z/` ran before the checkbox and identity-completeness fixes. Its Cloudflare screenshot visibly shows widget success, while the saved report says `pending`; identity records the observed DNS mismatch but incorrectly has `complete: false` under the old semantics.
- `benchmarks/results/proxy-quality/20260721T120315.404689Z/` also ran before those fixes. Its Cloudflare screenshot shows an unchecked "Verify you are human" checkbox, while the saved report says `pending`; identity likewise has the old `complete: false` value.
- `benchmarks/results/proxy-quality/20260721T122352.699808Z/` ran after the checkbox and identity-completeness fixes but before the multi-input token-probe fix. Its Cloudflare screenshot visibly shows success and is byte-identical to the first run's success screenshot, while the saved report still says `pending`; identity correctly has `complete: true`, `aligned: false`, and a local-DNS mismatch.
- `benchmarks/results/proxy-quality/20260721T123856.982677Z/` ran after the multi-input token-probe fix. It correctly records Cloudflare `passed`, Google `captcha`, complete identity evidence, WebRTC alignment, the expected SOCKS5 local-DNS mismatch, AS3257 evidence, and summary `blocked` / unsuitable `no`.

All three recorded connectivity success with agreement across IPify/AWS/IPify, all required reputation sources available with no listed match, AS3257 / `GTT-BACKBONE GTT` evidence retained as `unknown`/`low`, SOCKS5 local-DNS mismatch, Google `captcha`, both screenshots captured, and summary `blocked` / unsuitable `no`. The first two reports preserve pre-checkbox/pre-completeness parser output, and the third preserves pre-multi-input-token-probe output; none is rewritten after collection. Sanitized deterministic fixtures now cover token success (including multiple inputs with only a later input populated), a visible checkbox, and an indeterminate widget without storing a sitekey, token, or page HTML.

Cache reuse is demonstrated by byte-identical `sources.json` files across all three runs (SHA-256 `15722f67cbe644bde4ea832d75eefb9c89d7aa3f3451a1c19f4afea4569f246e`) and unchanged per-source provenance. The second and third runs therefore reused the cache populated before the first:

| Source | Retrieved UTC | SHA-256 |
|---|---|---|
| IPsum | `2026-07-21T11:06:04Z` | `569c3f5a72801ae8230904c42cc3e80f64fd3da413b37e5ff98171d60cc152f3` |
| FireHOL level 1 | `2026-07-21T11:06:05Z` | `1ce9882de1a6e01c7ce6b41d755f14c094b33ce98238e0d0addc5eeedc80d305` |
| FireHOL level 2 | `2026-07-21T11:06:05Z` | `0df2fee7da3e8a5df2a5b26b47ce9c3dc8cf92ef6ec46acd877034b573db1c61` |
| Sapics | `2026-07-21T11:06:09Z` | `75713dd5e797eef3f41cab9fef6c7fd2ffa94a2053e90e0d7a171b67102560dd` |

Privacy acceptance passed: actual username/password scans across all three controlled runs' `report.json` and `sources.json` artifacts returned no matches. Independent structural inspection found only masked proxy userinfo, no authorization headers, cookies, CAPTCHA response values, HTML bodies, profile paths, or browser storage. All six proxy-run PNGs and the direct-control PNG were valid through `IEND` and contained only `IHDR`, `IDAT`, and `IEND` chunks.

## Files changed

- Scanner: `benchmarks/proxy_quality_models.py`, `benchmarks/proxy_intelligence.py`, `benchmarks/proxy_auth_relay.py`, `benchmarks/proxy_site_checks.py`, `benchmarks/proxy_quality.py`.
- Deterministic tests: `tests/test_proxy_quality_models.py`, `tests/test_proxy_intelligence.py`, `tests/test_proxy_auth_relay.py`, `tests/test_proxy_site_checks.py`, `tests/test_proxy_quality_cli.py`.
- Documentation/ledger: `README.md`, `docs/CODEBASE_FUNCTIONALITY.md`, `docs/superpowers/specs/2026-07-21-proxy-quality-scanner-design.md`, `docs/superpowers/plans/2026-07-21-proxy-quality-scanner.md`, `.superpowers/sdd/progress.md`.
- Supporting audits: `.superpowers/sdd/final-fix-checklist.md`, `.superpowers/sdd/proxy-auth-investigation.md`, `.superpowers/sdd/relay-implementation-report.md`, `.superpowers/sdd/final-fix-review.md`.

No Git commands or commits were used.

## Remaining caveat

The classifier remains `unknown` / `low` because open ASN data identifies AS3257 / GTT backbone but provides no structured residential, mobile, ISP, or hosting category. This is intentionally conservative; optional IPinfo enrichment can provide stronger type evidence. Earlier reports remain unchanged for auditability, and no credential value is recorded here.
