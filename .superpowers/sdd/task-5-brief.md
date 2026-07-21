### Task 5: CLI orchestration, safe report writing, and exit codes

Create `benchmarks/proxy_quality.py` and `tests/test_proxy_quality_cli.py`; modify `benchmarks/__init__.py` only if required.

Consume the existing Task 1-4 interfaces. Produce:

- `run_proxy_quality_scan(proxy: str, output_dir: Path, *, browser_checks: bool, ipinfo_token: str | None) -> dict[str, object]`.
- CLI `python -m benchmarks.proxy_quality`.

Execution order:

1. Read/validate environment.
2. Resolve exit IP/latency.
3. Collect intelligence with per-source isolation.
4. Classify network.
5. Run or skip browser checks.
6. Aggregate summary.
7. Build secret set from raw proxy and parsed username/password.
8. Run `assert_no_secrets()` on report and console payload.
9. Write JSON atomically via sibling `.tmp`, flush/fsync, replace.
10. Print only redacted endpoint, summary, and artifact path.

CLI rules/tests:

- Proxy comes only from `CLOAK_TEST_PROXY`; never CLI argument.
- Missing proxy exits 2 without environment contents.
- Connectivity failure exits 3.
- Artifact write failure exits 4.
- Bad reputation is a valid completed scan and exits 0.
- `PROXY_QUALITY_SKIP_BROWSER=1` produces site `skipped` and summary `unknown` unless intelligence/alignment makes it questionable/blocked.
- Timestamped output contains `report.json` and `sources.json`.
- Nested credentials abort before final replace.
- Use `tempfile.TemporaryDirectory()` for browser profile and ensure it is removed after context closes.
- Output screenshots live only inside timestamped artifact directory.
- Never serialize raw proxy/token, cookies, HTML, headers, CAPTCHA tokens, or profile paths/storage.
- Catch known configuration/connectivity/artifact exceptions and scrub unexpected exception text before printing.

Report sections: `connectivity`, `classification`, `reputation_intelligence`, `identity_alignment`, `site_outcomes`, `summary`, `proxy` (redacted only), `timestamp_utc`, `sources_manifest`. The separate `sources.json` contains safe source provenance only.

Global constraints:

- `clean_observed` is timestamp/site-specific.
- One initial browser navigation per protected site and no CAPTCHA interaction (delegated to Task 4).
- Deterministic tests must monkeypatch all network/browser calls.
- Follow TDD with RED/GREEN evidence.
- This is not Git; do not commit.

Verification:

```powershell
python -m pytest tests/test_proxy_quality_cli.py -q
python -m pytest tests/test_proxy_quality_models.py tests/test_proxy_intelligence.py tests/test_proxy_site_checks.py tests/test_proxy_quality_cli.py tests/test_fingerprint_scanners.py -q
python -m py_compile benchmarks/proxy_quality.py
```

Write full report to `.superpowers/sdd/task-5-report.md`.
