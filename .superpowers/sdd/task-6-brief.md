### Task 6: Documentation and deterministic verification

Modify `README.md` and `docs/CODEBASE_FUNCTIONALITY.md`. Do not run the credentialed live scan; the controller will perform it after review so credentials never enter agent reports.

Document these commands:

```powershell
python -m pip install -e ".[geoip]"
$env:CLOAK_TEST_PROXY = "socks5://user:password@host:port"
python -m benchmarks.proxy_quality

$env:PROXY_QUALITY_SKIP_BROWSER = "1"
python -m benchmarks.proxy_quality
```

Explain:

- `type`: `mobile`, `residential_or_isp`, `datacenter_or_hosting`, or `unknown`.
- `type_confidence`: high/medium/low; heuristic-only can never be high.
- `reputation`: clean_observed/questionable/blocked/unknown.
- `suitable_for_protected_sites`: yes/no/uncertain.
- Network type and reputation are independent: residential/mobile does not imply clean; datacenter does not automatically imply blocked.
- `clean_observed` is timestamped and site-specific, never universal/permanent.
- Browser checks make one initial navigation each to the Cloudflare third-party Turnstile demo and Google, never click/solve CAPTCHA, and can be skipped.
- Credentials are environment-only and reports contain a redacted endpoint.
- Datasets are cached with provenance/checksum.
- Attribute/link: ipinfo/cli (Apache-2.0, optional API), sapics/ip-location-db with per-dataset licensing, stamparm/ipsum (Unlicense), and FireHOL blocklist-ipsets with source-specific licenses. Explain source availability limitations.
- Link the design/spec and implementation files in the functionality guide/source map.

Run fresh deterministic verification:

```powershell
python -m py_compile benchmarks/proxy_quality_models.py benchmarks/proxy_intelligence.py benchmarks/proxy_site_checks.py benchmarks/proxy_quality.py
python -m pytest tests/test_proxy_quality_models.py tests/test_proxy_intelligence.py tests/test_proxy_site_checks.py tests/test_proxy_quality_cli.py tests/test_fingerprint_scanners.py -q
python -m pytest tests/test_fingerprint_preset.py tests/test_session.py tests/test_launch.py tests/test_persistent_context.py -q
```

Global constraints:

- Never include real proxy details or credentials in docs/report.
- Do not claim a live result; controller has not run it yet.
- Do not modify production code/tests.
- This is not Git; do not commit.

Write full report to `.superpowers/sdd/task-6-report.md`.
