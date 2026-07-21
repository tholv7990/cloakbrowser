# Task 5 report: proxy-quality CLI orchestration and safe artifacts

## Status and scope

Implemented Task 5 in the brief-listed files:

- Created `benchmarks/proxy_quality.py`.
- Created `tests/test_proxy_quality_cli.py`.
- Created this report at `.superpowers/sdd/task-5-report.md`.
- Left `benchmarks/__init__.py` unchanged because package-level exports were not required.
- Performed no Git operations or commits; the workspace is not a Git repository.

## Implementation

`run_proxy_quality_scan()` now validates the proxy, resolves the exit IP and latency, collects the existing isolated intelligence sources, classifies the network, optionally runs the existing passive browser checks, aligns provider-observed IP fields with the resolved exit IP, and aggregates the existing report summary.

The serialized `report.json` has exactly these sections: `connectivity`, `classification`, `reputation_intelligence`, `identity_alignment`, `site_outcomes`, `summary`, `proxy`, `timestamp_utc`, and `sources_manifest`. The returned in-memory dictionary additionally exposes `artifact_path` for CLI handoff, but that field is not added to `report.json`. `sources.json` is a separate list containing only allowlisted provenance fields. Connectivity, intelligence, and browser results are also projected through allowlists, so downstream headers, cookies, raw HTML, CAPTCHA tokens, raw source payloads, and profile/storage fields cannot enter the artifacts.

Each run creates a unique UTC timestamped directory. Browser screenshots are directed only to its `screenshots` child. Browser profiles use `tempfile.TemporaryDirectory()`; the existing browser checker closes its context before returning, and the temporary profile is removed as the orchestrator leaves the context manager.

The report and console payload are checked with `assert_no_secrets()` before any final artifact replacement. The guarded values include the credential-bearing raw proxy, parsed username/password in encoded and decoded forms, and the optional IPinfo token. A detected nested secret raises an artifact/configuration-safe error before either `.tmp` file is staged or replaced.

Both JSON outputs are written to sibling `sources.json.tmp` and `report.json.tmp` files, flushed, passed through `os.fsync()`, and replaced in that order. Temporary files are removed after failure. Because every run uses a new timestamped directory, a failure on the second replace also removes the first final file rather than leaving a partial artifact set.

The module CLI accepts no arguments and reads the proxy only from `CLOAK_TEST_PROXY`. It validates `PROXY_QUALITY_SKIP_BROWSER` as `0` or `1`, reads optional `IPINFO_TOKEN`, and prints a single JSON object containing only the redacted proxy endpoint, summary, and report artifact path. Static scrubbed errors implement these exit codes:

- `0`: completed scan, including blocked/questionable reputation outcomes.
- `2`: missing/invalid environment configuration or attempted CLI arguments.
- `3`: proxy connectivity failure.
- `4`: unsafe or failed artifact creation.
- `1`: scrubbed unexpected failure.

With browser checks skipped, both site outcomes are `skipped`. The existing summary model therefore returns `unknown` for otherwise aligned/clean intelligence, while high-confidence reputation matches remain `blocked`, other matches remain `questionable`, and identity or exit-IP disagreement remains `questionable`.

## Offline test coverage

The 16 CLI/orchestration tests monkeypatch every network and browser boundary. They cover:

- timestamped `report.json` and `sources.json` generation;
- exact serialized report sections and safe source provenance;
- Task 1–4 orchestration, classification, identity alignment, verdict flattening, and summary aggregation;
- temporary profile lifetime and screenshot directory placement;
- skipped browser checks and unknown/questionable/blocked precedence;
- rejection of nested and percent-encoded credentials before replacement;
- removal of non-allowlisted headers, cookies, source payloads, CAPTCHA tokens, and arbitrary browser HTML;
- sibling `.tmp`, flush/fsync, replacement order, cleanup, and partial-final rollback;
- missing proxy, rejected proxy arguments, connectivity/artifact/unexpected failures, fixed exit codes, and scrubbed output;
- completed bad-reputation scans exiting zero with only the safe console payload.

## TDD evidence

1. Initial RED: `python -m pytest tests/test_proxy_quality_cli.py -q` failed during collection with `ModuleNotFoundError: No module named 'benchmarks.proxy_quality'` before production code existed.
2. Initial GREEN iteration: the first implementation produced `11 passed, 1 failed`; the only failure showed the guard raised the correct safe exception but its message omitted the required word `secret`. The minimal message correction produced `12 passed`.
3. Safety-edge RED: focused tests for arbitrary browser HTML and second-replace rollback both failed. The raw HTML appeared as both site verdicts, and `sources.json` remained after the simulated `report.json` replacement failure.
4. Safety-edge GREEN: verdict allowlisting and finalized-file rollback produced `2 passed`; the complete focused suite then produced `14 passed`.
5. Credential-edge RED: the percent-encoded username test did not raise, and the formatted chained filesystem traceback exposed `scan-password` from a credential-bearing path.
6. Credential-edge GREEN: guarding encoded and decoded credential components plus suppressing internal exception chains produced `2 passed`; the complete focused suite then produced `16 passed`.

## Final verification

Fresh verification after the final refactor completed successfully:

```text
python -m pytest tests/test_proxy_quality_cli.py -q
16 passed in 0.19s

python -m pytest tests/test_proxy_quality_models.py tests/test_proxy_intelligence.py tests/test_proxy_site_checks.py tests/test_proxy_quality_cli.py tests/test_fingerprint_scanners.py -q
67 passed in 1.55s

python -m py_compile benchmarks/proxy_quality.py
exit code 0
```

## Self-review and concerns

The final review checked every brief requirement against code and tests: environment-only proxy input, execution order, per-source isolation boundary, classification, browser run/skip behavior, summary precedence, secret set and guards, atomic writes, restricted console output, exit codes, timestamped artifacts, profile/screenshot containment, safe serialized fields, and exception scrubbing. No requirement gap remains in the implemented scope.

Operationally, `clean_observed` remains deliberately limited to the timestamp and the two recorded site outcomes in that report; it is not a durable or universal reputation guarantee. Browser verdicts can safely degrade to `error`/`unknown` after site redesigns, and unavailable third-party intelligence sources remain visible as unavailable provenance rather than failing the scan. The optional IPinfo source remains disabled without `IPINFO_TOKEN`.

## Reviewer follow-up: browser artifact filesystem errors

The reviewer identified that `run_browser_checks()` creates its screenshot output directory before its own browser exception handling. An `OSError` from that filesystem step therefore crossed the Task 4 boundary and reached the CLI as an unexpected failure with exit code 1, even though the failure was specifically artifact preparation and should exit 4.

A CLI-level offline regression now executes the real `run_browser_checks()` through `main()` and `run_proxy_quality_scan()`, while monkeypatching only `Path.mkdir()` for the timestamped `screenshots` directory. The injected `OSError` contains the proxy password to prove that the emitted CLI error remains scrubbed. RED produced `assert 1 == 4` and `Unexpected proxy-quality failure`. The minimal fix wraps `OSError` from temporary-profile setup or `run_browser_checks()` invocation in a cause-suppressed `ArtifactWriteError`; GREEN produces exit 4 with the static artifact error and no credential text.

Skipped-browser coverage now also supplies a FireHOL level 2 `other_matches` result and verifies `site_outcomes` remain `skipped`, reputation becomes `questionable`, and suitability remains `unknown`.

Fresh reviewer verification completed successfully:

```text
python -m pytest tests/test_proxy_quality_cli.py -q
18 passed in 0.20s

python -m pytest tests/test_proxy_quality_models.py tests/test_proxy_intelligence.py tests/test_proxy_site_checks.py tests/test_proxy_quality_cli.py tests/test_fingerprint_scanners.py -q
69 passed in 1.66s

python -m py_compile benchmarks/proxy_quality.py
exit code 0
```
