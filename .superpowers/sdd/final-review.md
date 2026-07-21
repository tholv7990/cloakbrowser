# Proxy Quality Scanner Final Review

Read-only review complete; no production files were modified and no tests were rerun.

## Readiness verdict

**NOT READY.** The live `blocked` reputation is supported by the Google `/sorry/` outcome, and the saved JSON/visible screenshot show no credential leak. However, the scanner can expose credentials at runtime, can emit unsupported `clean_observed`, does not implement browser identity checks, and cannot produce one required network type.

## Critical

### 1. Credential safety is broken in two ways

- Redaction splits at the first `@` (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality_models.py:52-55`, `:194-209`), while CloakBrowser supports raw `@` in passwords and parses the last `@` as the authority delimiter (`C:\Users\Admin\Desktop\CloakBrowser\tests\test_proxy.py:316-320`). For example, `socks5://user:p@ss@host:1080` becomes `socks5://***:***@ss@host:1080`, leaking a password suffix. `_build_secret_set()` checks the full password, not leaked substrings (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality.py:89-120`), so the guard does not catch it. The scanner test covers only simple credentials (`C:\Users\Admin\Desktop\CloakBrowser\tests\test_proxy_quality_models.py:82-84`).
- Browser-enabled scans pass the raw proxy to `launch_persistent_context()` (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_site_checks.py:93-101`). CloakBrowser then places credentialed SOCKS URLs—and some credentialed HTTP URLs—into Chromium's `--proxy-server=` process argument (`C:\Users\Admin\Desktop\CloakBrowser\cloakbrowser\browser.py:1523-1568`). That defeats the design's reason for environment-only input: credentials are visible in process listings and possibly crash diagnostics (`C:\Users\Admin\Desktop\CloakBrowser\docs\superpowers\specs\2026-07-21-proxy-quality-scanner-design.md:23`).
- Validation also permits path/query/fragment suffixes (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_intelligence.py:96-115`); when userinfo is absent, those values are printed unchanged and excluded from the secret set (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality_models.py:194-209`, `C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality.py:105-120`, `:312-325`).

Fix redaction by reconstructing from parsed scheme/host/port, reject path/query/fragment and malformed authority, add special-character tests, and use a credential-free browser launch mechanism such as a local authenticated relay or secure core proxy-auth path.

### 2. Identity alignment is a vacuous false positive; the specified leak stage does not exist

- `_identity_alignment()` inspects IP fields from ASN/IPinfo signals and declares no observations aligned: `not observed or ...` (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality.py:183-200`).
- `run_browser_checks()` returns only Google/Cloudflare verdicts (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_site_checks.py:78-117`); it never observes WebRTC, timezone, locale, or DNS.
- `clean_observed` accepts this fabricated alignment (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality_models.py:165-183`).
- The live report proves the issue: `"aligned": true` with `"observed_ips": []` (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\results\proxy-quality\20260721T110600.808211Z\report.json:17-20`).
- Tests encode the false premise (`C:\Users\Admin\Desktop\CloakBrowser\tests\test_proxy_quality_models.py:61-69`, `C:\Users\Admin\Desktop\CloakBrowser\tests\test_proxy_quality_cli.py:182-204`).
- The plan dropped the design's identity stage: Task 4 specifies only protected-site checks (`C:\Users\Admin\Desktop\CloakBrowser\docs\superpowers\plans\2026-07-21-proxy-quality-scanner.md:287-347`), despite the design requirement (`C:\Users\Admin\Desktop\CloakBrowser\docs\superpowers\specs\2026-07-21-proxy-quality-scanner-design.md:73-82`).

Make alignment tri-state, collect source-attributed HTTP/WebRTC IP, timezone, locale, and DNS observations, and require complete evidence for `clean_observed`; missing evidence must yield `unknown`, while an actual mismatch remains `questionable`.

### 3. Unavailable intelligence sources can silently produce `clean_observed`

- Unavailable sources receive empty matches (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_intelligence.py:463-477`, `:494-506`).
- Orchestration discards source availability when building `reputation_intelligence` (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality.py:298-305`).
- Summarization treats those empty arrays exactly like successful negative checks (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality_models.py:162-185`).

Thus all selected abuse sources may fail while passing browser outcomes yield `clean_observed`, contradicting `C:\Users\Admin\Desktop\CloakBrowser\docs\superpowers\specs\2026-07-21-proxy-quality-scanner-design.md:34`, `:117` and the documentation's explicit claims (`C:\Users\Admin\Desktop\CloakBrowser\README.md:1392`, `C:\Users\Admin\Desktop\CloakBrowser\docs\CODEBASE_FUNCTIONALITY.md:379`). Propagate required-source status and require successful selected-list checks before a clean verdict. No current test covers unavailable-source verdict aggregation.

### 4. The required classifier is incomplete and discards its evidence

- `NetworkType` omits `residential_or_isp` (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality_models.py:15-21`), and classification has no ISP/residential branch (`:93-147`).
- Sapics successfully identifies the live exit range as AS3257/GTT (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\results\proxy-quality\.cache\sapics-2.3.2026061719-ipv4.csv:302849`), but signals are used transiently and never serialized (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_intelligence.py:614-630`, `C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality.py:280-315`).
- The live artifact therefore says unknown/low and contains no ASN evidence (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\results\proxy-quality\20260721T110600.808211Z\report.json:2-6`, `:68-77`).
- The exact report-key test entrenches the evidence omission (`C:\Users\Admin\Desktop\CloakBrowser\tests\test_proxy_quality_cli.py:95-105`).

Add the enum and structured ISP/residential logic. AS3257 need not be mislabeled residential merely because it is a backbone ASN, but the report must retain the ASN evidence and explain why the result is unknown if that remains the result.

## Important

### 5. Classification conflicts can still receive high confidence

Conflicts are recorded at `C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality_models.py:122-124`, but majority branches return medium/high at `:134-145`; `C:\Users\Admin\Desktop\CloakBrowser\tests\test_proxy_quality_models.py:40-51` explicitly expects high despite a conflict. The design requires low confidence whenever sources conflict (`C:\Users\Admin\Desktop\CloakBrowser\docs\superpowers\specs\2026-07-21-proxy-quality-scanner-design.md:62`).

### 6. Public summary schema is incompatible with the specification and docs

`Suitability.UNKNOWN` emits `"unknown"` rather than `"uncertain"` (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality_models.py:40-45`), and `summarize_report()` omits summary `type` and `type_confidence` entirely (`:154-191`). Tests enforce the wrong suitability (`C:\Users\Admin\Desktop\CloakBrowser\tests\test_proxy_quality_cli.py:127-179`). The contract is at `C:\Users\Admin\Desktop\CloakBrowser\docs\superpowers\specs\2026-07-21-proxy-quality-scanner-design.md:105-110`, `C:\Users\Admin\Desktop\CloakBrowser\README.md:1383-1386`, and `C:\Users\Admin\Desktop\CloakBrowser\docs\CODEBASE_FUNCTIONALITY.md:370-373`.

### 7. The documented CLI interface rejects `--output-dir`

`main()` rejects every argument and hardcodes the output root (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality.py:334-357`), while the design and live-verification plan require `--output-dir` (`C:\Users\Admin\Desktop\CloakBrowser\docs\superpowers\specs\2026-07-21-proxy-quality-scanner-design.md:13-16`, `C:\Users\Admin\Desktop\CloakBrowser\docs\superpowers\plans\2026-07-21-proxy-quality-scanner.md:464-470`). The CLI test approves blanket rejection (`C:\Users\Admin\Desktop\CloakBrowser\tests\test_proxy_quality_cli.py:376-383`).

### 8. Connectivity evidence is incomplete

Two successes from the same alternating endpoint satisfy connectivity (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_intelligence.py:161-179`); only raw latency values are reported, with no median or country consistency (`:180-185`). This violates `C:\Users\Admin\Desktop\CloakBrowser\docs\superpowers\specs\2026-07-21-proxy-quality-scanner-design.md:42-45`. Track endpoint identity, require both services, calculate the median, and record geographic consistency or explicit unavailability.

### 9. Reputation evidence lacks required semantics

Matches contain only source/network (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_intelligence.py:619-628`, `C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality.py:141-152`), not list category or exact-IP-versus-CIDR granularity required by `C:\Users\Admin\Desktop\CloakBrowser\docs\superpowers\specs\2026-07-21-proxy-quality-scanner-design.md:68-70`.

### 10. Cloudflare's explicit-block summary branch is unreachable

Its parser cannot return `blocked` (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_site_checks.py:61-75`), although aggregation treats that state as decisive (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality_models.py:178-180`). Add safe URL/status/body block indicators.

### 11. Live acceptance evidence is incomplete

- No direct-network Google control artifact exists, despite `C:\Users\Admin\Desktop\CloakBrowser\docs\superpowers\specs\2026-07-21-proxy-quality-scanner-design.md:172`; Task 6 omitted this success criterion (`C:\Users\Admin\Desktop\CloakBrowser\docs\superpowers\plans\2026-07-21-proxy-quality-scanner.md:464-476`).
- Cloudflare is `pending`, but no `cloudflare.png` exists. Pending polling consumes the entire deadline before screenshot capture (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_site_checks.py:154-173`, `:281-289`), and the test expects missing screenshots on timeout (`C:\Users\Admin\Desktop\CloakBrowser\tests\test_proxy_site_checks.py:134-169`).
- The report discards screenshot-capture status (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality.py:203-211`).
- The ledger stops at Task 5 (`C:\Users\Admin\Desktop\CloakBrowser\.superpowers\sdd\progress.md:9`).

### 12. Documentation overstates offline behavior

README calls skip-browser mode deterministic/offline (`C:\Users\Admin\Desktop\CloakBrowser\README.md:1368`, `:1390`), but it still performs proxy echo requests and potentially dataset downloads (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality.py:273-280`). It also does not explain the full two-source/one-source/conflict confidence rules required by `C:\Users\Admin\Desktop\CloakBrowser\docs\superpowers\specs\2026-07-21-proxy-quality-scanner-design.md:159-166`.

## Minor

- `_non_empty()` accepts empty mappings/sequences and arbitrary objects as mobile evidence (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality_models.py:58-72`). Normalize and type-check provider fields.
- Browser artifacts use a `screenshots/` subdirectory rather than the specified top-level names, and reports omit the Pixelscan link and third-party-demo qualification (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality.py:283-315`; `C:\Users\Admin\Desktop\CloakBrowser\docs\superpowers\specs\2026-07-21-proxy-quality-scanner-design.md:90`, `:123-130`).
- Screenshot metadata is not inspected by the secret guard (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_quality.py:214-221`, `:324-326`; `C:\Users\Admin\Desktop\CloakBrowser\benchmarks\proxy_site_checks.py:281-289`). No leak was observed in the current PNG, but metadata stripping/validation needs an acceptance test.
- Tests use mocked transports/pages rather than a local HTTP/SOCKS integration fixture, leaving proxy transport configuration and cross-module evidence flow untested.

## Consolidated fix order

1. Eliminate process-argument credential exposure and repair parsing/redaction.
2. Implement real, tri-state browser identity/leak evidence.
3. Gate clean verdicts on required source availability.
4. Complete all four network types and serialize sanitized classification evidence.
5. Correct conflict confidence and the summary schema.
6. Implement safe `--output-dir`.
7. Complete connectivity and reputation evidence fields.
8. Add reachable Cloudflare block handling and reliable screenshots.
9. Add direct-network control evidence.
10. Rewrite affected tests and correct README/functionality documentation and the task ledger.

## Positive evidence

Cache provenance, source isolation, atomic JSON writes, exception scrubbing, browser-response whitelisting, and ordinary proxy redaction have strong focused tests. The live report's `blocked` summary is internally consistent with Google `captcha` (`C:\Users\Admin\Desktop\CloakBrowser\benchmarks\results\proxy-quality\20260721T110600.808211Z\report.json:28`, `:93`), and the saved report and visible Google screenshot contain no observed proxy credential, cookie, authorization header, HTML body, storage state, or CAPTCHA response token. Those positives do not offset the critical readiness blockers above.
