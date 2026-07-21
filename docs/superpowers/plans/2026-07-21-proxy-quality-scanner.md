# Proxy Quality Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a credential-safe standalone CLI that classifies a proxy as mobile, residential/ISP, datacenter/hosting, or unknown and separately measures its observed reputation through trusted intelligence and limited browser checks.

**Architecture:** Keep deterministic models and verdict aggregation independent from network adapters. Resolve the exit IP first, enrich it through cached open-source datasets and optional IPinfo data, then run one Cloudflare and one Google browser check through a dedicated CloakBrowser profile. Serialize a timestamped report only after recursively checking that no credential material is present.

**Tech Stack:** Python 3.10+, pytest, httpx with optional `socksio`, Playwright through CloakBrowser, `ipaddress`, JSON, cached IPsum/FireHOL/sapics datasets, optional IPinfo HTTP API.

## Global Constraints

- Read proxy credentials only from `CLOAK_TEST_PROXY`; never accept them as CLI arguments.
- Never log or serialize proxy usernames, passwords, authentication headers, cookies, CAPTCHA tokens, or browser storage.
- Public exit IPs may appear because they are the subject of the report.
- Send at most one initial browser request to Cloudflare and one to Google per scan; never solve or click a CAPTCHA.
- Treat `clean_observed` as a timestamped site-specific observation, never a permanent or universal claim.
- Classification based only on ASN-name heuristics has `low` confidence.
- Live tests are opt-in; deterministic unit tests require no internet access.
- The workspace is not a Git repository, so replace commit steps with explicit verification checkpoints.

---

## File map

- Create `benchmarks/proxy_quality_models.py`: enums, typed report structures, classification and summary aggregation, recursive secret guard.
- Create `benchmarks/proxy_intelligence.py`: proxy connectivity, dataset cache, parsers, CIDR matching, sapics/IPsum/FireHOL/IPinfo adapters.
- Create `benchmarks/proxy_site_checks.py`: CloakBrowser leak, Cloudflare, and Google page-state checks.
- Create `benchmarks/proxy_quality.py`: CLI, orchestration, exit codes, artifact creation.
- Create `tests/test_proxy_quality_models.py`: deterministic classification, summary, and redaction tests.
- Create `tests/test_proxy_intelligence.py`: parser, CIDR, cache, connectivity, and partial-source tests.
- Create `tests/test_proxy_site_checks.py`: sanitized page-state parser tests.
- Create `tests/fixtures/proxy_quality/`: small source/page fixtures containing no real proxy, token, or cookie data.
- Modify `README.md`: usage, interpretation, dependencies, licenses, and limitations.
- Modify `docs/CODEBASE_FUNCTIONALITY.md`: source map and scanner behavior.

---

### Task 1: Deterministic report model and secret guard

**Files:**
- Create: `benchmarks/proxy_quality_models.py`
- Create: `tests/test_proxy_quality_models.py`

**Interfaces:**
- Produces `NetworkType`, `Confidence`, `Reputation`, and `Suitability` string enums.
- Produces `classify_network(signals: list[dict[str, object]]) -> dict[str, object]`.
- Produces `summarize_report(report: dict[str, object]) -> dict[str, str]`.
- Produces `redact_proxy(proxy: str) -> str` by reusing the existing scanner behavior without importing browser code.
- Produces `assert_no_secrets(value: object, secrets: set[str]) -> None`.

- [ ] **Step 1: Write failing model tests**

```python
from benchmarks.proxy_quality_models import (
    assert_no_secrets,
    classify_network,
    redact_proxy,
    summarize_report,
)


def test_two_mobile_signals_are_high_confidence():
    result = classify_network([
        {"source": "ipinfo", "is_mobile": True, "carrier": "Example Mobile"},
        {"source": "asn", "asn_type": "isp", "mcc": "452"},
    ])
    assert result["type"] == "mobile"
    assert result["type_confidence"] == "high"
    assert result["conflicts"] == []
    assert [item["source"] for item in result["evidence"]] == ["ipinfo", "asn"]


def test_hosting_asn_name_heuristic_is_low_confidence():
    result = classify_network([
        {"source": "sapics", "asn": "AS64500", "organization": "Example Cloud Hosting"},
    ])
    assert result["type"] == "datacenter_or_hosting"
    assert result["type_confidence"] == "low"


def test_clean_observed_requires_all_live_signals():
    summary = summarize_report({
        "connectivity": {"success": True, "exit_ip_agreement": True},
        "classification": {"type": "mobile", "type_confidence": "high"},
        "reputation_intelligence": {
            "high_confidence_matches": [],
            "other_matches": [],
            "required_sources_available": True,
        },
        "identity_alignment": {
            "status": "aligned", "aligned": True, "complete": True,
            "http_exit_ip": {"matches": True}, "webrtc": {"matches": True},
            "timezone": {"matches": True}, "locale": {"matches": True},
            "dns": {"matches": True},
        },
        "site_outcomes": {
            "cloudflare": {"verdict": "passed"},
            "google": {"verdict": "results"},
        },
    })
    assert summary["type"] == "mobile"
    assert summary["type_confidence"] == "high"
    assert summary["reputation"] == "clean_observed"
    assert summary["suitable_for_protected_sites"] == "yes"


def test_secret_guard_rejects_nested_password():
    try:
        assert_no_secrets({"nested": ["sample-password"]}, {"sample-password"})
    except ValueError as exc:
        assert "secret" in str(exc).lower()
    else:
        raise AssertionError("secret was not rejected")


def test_proxy_redaction_supports_uri_and_colon_formats():
    assert redact_proxy("socks5://u:p@203.0.113.8:1080") == "socks5://***:***@203.0.113.8:1080"
    assert redact_proxy("203.0.113.8:1080:u:p") == "203.0.113.8:1080:***:***"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_proxy_quality_models.py -q`

Expected: collection fails because `benchmarks.proxy_quality_models` does not exist.

- [ ] **Step 3: Implement enums, classification evidence, summary precedence, redaction, and recursive scanning**

Implement the exact precedence:

```python
if google in {"captcha", "blocked"} or cloudflare in {"interactive", "blocked"} or high_matches:
    reputation = "blocked"
elif other_matches or not exit_ip_agreement or identity_mismatch:
    reputation = "questionable"
elif required_sources_available and complete_identity_evidence and all_required_checks_pass:
    reputation = "clean_observed"
else:
    reputation = "unknown"
```

Classification must count independent structured sources, record conflicts, and use ASN-name terms only as a low-confidence fallback. Include hosting terms (`hosting`, `cloud`, `datacenter`, `data center`, `vps`) and mobile structured fields (`is_mobile`, `carrier`, `mcc`, `mnc`); do not classify an arbitrary organization containing `telecom` as mobile.

- [ ] **Step 4: Run model tests and verify GREEN**

Run: `python -m pytest tests/test_proxy_quality_models.py -q`

Expected: all tests pass.

- [ ] **Step 5: Verification checkpoint**

Run: `python -m py_compile benchmarks/proxy_quality_models.py`

Expected: exit code 0.

---

### Task 2: Connectivity and cache primitives

**Files:**
- Create: `benchmarks/proxy_intelligence.py`
- Create: `tests/test_proxy_intelligence.py`
- Create: `tests/fixtures/proxy_quality/ipify.json`

**Interfaces:**
- Consumes `redact_proxy` from Task 1.
- Produces `validate_proxy_url(value: str) -> None`.
- Produces `resolve_exit_ip(proxy: str, *, attempts: int = 3) -> dict[str, object]`.
- Produces `DatasetCache(root: Path, max_age: timedelta)` with `get(url: str, name: str) -> Path`.
- Produces `sha256_file(path: Path) -> str`.

- [ ] **Step 1: Write failing validation and cache tests**

Use `pytest` monkeypatch with a fake `httpx.Client` so no request leaves the machine. Cover:

```python
def test_validate_proxy_rejects_credentials_without_host():
    with pytest.raises(ValueError, match="host"):
        validate_proxy_url("socks5://user:pass@")


def test_resolve_exit_ip_requires_echo_agreement(monkeypatch):
    responses = iter(["203.0.113.10", "203.0.113.10", "203.0.113.11"])
    monkeypatch.setattr("benchmarks.proxy_intelligence._fetch_echo_ip", lambda *a, **k: next(responses))
    result = resolve_exit_ip("socks5://u:p@proxy.example:1080", attempts=3)
    assert result["exit_ip"] == "203.0.113.10"
    assert result["exit_ip_agreement"] is False
    assert len(result["latency_ms"]) == 3


def test_cache_reuses_fresh_file(tmp_path, monkeypatch):
    cache = DatasetCache(tmp_path, timedelta(hours=24))
    existing = tmp_path / "ipsum.txt"
    existing.write_text("203.0.113.0/24\t3\n", encoding="utf-8")
    monkeypatch.setattr("benchmarks.proxy_intelligence._download_atomic", lambda *a: (_ for _ in ()).throw(AssertionError()))
    assert cache.get("https://example.invalid/ipsum.txt", "ipsum.txt") == existing
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_proxy_intelligence.py -q`

Expected: import failure or missing interface failures.

- [ ] **Step 3: Implement connectivity with existing dependency conventions**

Use `httpx.Client(proxy=proxy, timeout=10.0, follow_redirects=False)`. Query exactly three times, alternating these echo endpoints:

- `https://api.ipify.org?format=json`
- `https://checkip.amazonaws.com/`

Normalize each response through `ipaddress.ip_address`. Select the majority exit IP and set `exit_ip_agreement` only when every successful response agrees. Require at least two successful responses; otherwise raise `ProxyConnectivityError`. Document that SOCKS URLs require `pip install -e ".[geoip]"` for `socksio`.

- [ ] **Step 4: Implement atomic cached downloads**

`DatasetCache.get()` must:

1. Reuse a file younger than `max_age`.
2. Download to a sibling `.tmp` file.
3. Hash it before `Path.replace()`.
4. Store `<name>.meta.json` containing URL, UTC retrieval time, SHA-256, and byte count.
5. Remove the temporary file after any failure without deleting an older valid cache entry.

- [ ] **Step 5: Run connectivity tests and verify GREEN**

Run: `python -m pytest tests/test_proxy_intelligence.py -q`

Expected: all current tests pass.

---

### Task 3: Trusted intelligence adapters

**Files:**
- Modify: `benchmarks/proxy_intelligence.py`
- Modify: `tests/test_proxy_intelligence.py`
- Create: `tests/fixtures/proxy_quality/ipsum.txt`
- Create: `tests/fixtures/proxy_quality/firehol_level1.netset`
- Create: `tests/fixtures/proxy_quality/sapics_asn.csv`
- Create: `tests/fixtures/proxy_quality/ipinfo.json`

**Interfaces:**
- Produces `parse_network_list(path: Path, *, minimum_score: int | None = None) -> list[ipaddress._BaseNetwork]`.
- Produces `match_networks(ip: str, networks: list[ipaddress._BaseNetwork]) -> list[str]`.
- Produces `lookup_sapics_asn(ip: str, path: Path) -> dict[str, object] | None`.
- Produces `lookup_ipinfo(ip: str, token: str | None) -> dict[str, object] | None`.
- Produces `collect_intelligence(ip: str, cache: DatasetCache, token: str | None) -> dict[str, object]`.

- [ ] **Step 1: Add failing fixture parser tests**

Fixtures use documentation ranges only (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`). Tests must prove:

- Comments and blank lines are ignored.
- IPsum scores below 3 are excluded.
- IPv4 and IPv6 CIDRs work.
- The most specific matching sapics ASN range wins.
- Missing optional IPinfo token returns `None` without a network call.
- One failed source produces `status: unavailable` while other sources remain present.

- [ ] **Step 2: Run parser tests and verify RED**

Run: `python -m pytest tests/test_proxy_intelligence.py -q`

Expected: failures for the new missing functions.

- [ ] **Step 3: Implement source adapters with pinned URLs**

Use:

- IPsum: `https://raw.githubusercontent.com/stamparm/ipsum/master/ipsum.txt`
- FireHOL level 1: `https://raw.githubusercontent.com/firehol/blocklist-ipsets/master/firehol_level1.netset`
- FireHOL level 2: `https://raw.githubusercontent.com/firehol/blocklist-ipsets/master/firehol_level2.netset`
- sapics package metadata/data via `@ip-location-db/iptoasn-asn` on jsDelivr; resolve the current package version from its `package.json`, record that version in the manifest, and download its IPv4/IPv6 CSV assets selected from the package file list rather than guessing a filename.
- Optional IPinfo: `https://api.ipinfo.io/lite/{ip}?token=...` for basic ASN evidence; when the token's plan exposes `is_mobile`, `is_hosting`, privacy, or carrier fields, preserve them as structured signals. Never serialize the token or request URL.

Keep each source result shaped as:

```python
{
    "source": "ipsum",
    "status": "available",
    "retrieved_at": "2026-07-21T00:00:00Z",
    "sha256": "...",
    "matches": ["203.0.113.0/24"],
}
```

- [ ] **Step 4: Run adapter tests and verify GREEN**

Run: `python -m pytest tests/test_proxy_intelligence.py -q`

Expected: all tests pass without network access.

- [ ] **Step 5: Verify licenses/source manifest behavior**

Add constants for source repository, dataset URL, and license/attribution URL. Test that every enabled source appears in the generated manifest even when unavailable.

Run: `python -m pytest tests/test_proxy_intelligence.py -q`

Expected: all tests pass.

---

### Task 4: Credential-free browser identity and site-state checks without challenge interaction

**Files:**
- Create: `benchmarks/proxy_site_checks.py`
- Create: `benchmarks/proxy_auth_relay.py`
- Create: `tests/test_proxy_site_checks.py`
- Create: `tests/test_proxy_auth_relay.py`
- Create: `tests/fixtures/proxy_quality/google_results.txt`
- Create: `tests/fixtures/proxy_quality/google_captcha.txt`
- Create: `tests/fixtures/proxy_quality/cloudflare_passed.txt`
- Create: `tests/fixtures/proxy_quality/cloudflare_interactive.txt`

**Interfaces:**
- Produces `parse_google_state(url: str, body_text: str, *, search_container_visible: bool, recaptcha_visible: bool) -> str`.
- Produces `parse_cloudflare_state(body_text: str, *, token_present: bool, challenge_visible: bool) -> str`.
- Produces `AuthenticatedProxyRelay(proxy: str)`, a scoped loopback HTTP relay that keeps upstream credentials out of Chromium process arguments.
- Produces `run_browser_checks(proxy: str, profile_dir: Path, screenshot_dir: Path, *, expected_exit_ip: str | None) -> dict[str, object]` with tri-state HTTP/WebRTC/timezone/locale/DNS evidence.
- Produces `run_direct_google_control(profile_dir: Path, screenshot_path: Path) -> dict[str, object]` for a separate credential-free direct-network control.

- [ ] **Step 1: Write failing page-state parser tests**

```python
def test_google_results_text_that_mentions_recaptcha_is_not_a_challenge():
    state = parse_google_state(
        "https://www.google.com/search?q=test",
        "A search result discussing reCAPTCHA performance",
        search_container_visible=True,
        recaptcha_visible=False,
    )
    assert state == "results"


def test_google_sorry_redirect_is_captcha():
    assert parse_google_state(
        "https://www.google.com/sorry/index?continue=x",
        "Our systems have detected unusual traffic",
        search_container_visible=False,
        recaptcha_visible=True,
    ) == "captcha"


def test_cloudflare_token_without_interaction_passes():
    assert parse_cloudflare_state("Success!", token_present=True, challenge_visible=False) == "passed"
```

- [ ] **Step 2: Run parser tests and verify RED**

Run: `python -m pytest tests/test_proxy_site_checks.py -q`

Expected: import failure because the module does not exist.

- [ ] **Step 3: Implement strict page-state parsers**

Google priority: `/sorry/` or visible reCAPTCHA -> `captcha`; explicit access denial -> `blocked`; visible `#search` -> `results`; consent form -> `consent`; otherwise `unknown`. Never classify from the word `recaptcha` in arbitrary result text.

Cloudflare priority: token plus no visible challenge -> `passed`; visible challenge -> `interactive`; explicit error -> `error`; widget without verdict -> `pending`; otherwise `unknown`.

- [ ] **Step 4: Implement credential-free identity and single-request site flows**

For every browser-enabled proxy scan, start an authenticated relay on an ephemeral `127.0.0.1` port and pass only that credential-free endpoint to `launch_persistent_context()`. The relay supports authenticated HTTP/HTTPS CONNECT and SOCKS5/SOCKS5H, closes active sockets/workers after the browser context, and never logs or serializes its upstream credentials. Launch with a profile inside `tempfile.TemporaryDirectory()`, `fingerprint_preset="consistent"`, `args=["--fingerprint=63003"]`, `geoip=True`, and `humanize=True`.

Before protected-site checks, collect source-attributed browser HTTP exit IP, WebRTC candidate IP, timezone, locale, and whether proxy destination DNS was delegated upstream. Each dimension is `match`, `mismatch`, or unavailable; empty observations never imply alignment. Then visit each protected site once:

- Cloudflare Turnstile demo at `https://turnstiledemo.lusostreams.com/`: wait up to 20 seconds for pass/interactive/error state; do not click. Record that it is a third-party demonstration using Cloudflare's widget, not a universal Cloudflare reputation verdict.
- Google fixed query: wait up to 15 seconds for results/challenge/consent state; do not click.

Capture top-level `cloudflare.png` and `google.png` after state detection, reserving a separate screenshot timeout so a pending state cannot consume the capture budget. Validate PNG structure, strip nonessential metadata, and serialize verdict/capture status only; never persist token values, cookies, HTML, or storage state. Close the context in `finally`, then close the relay.

- [ ] **Step 5: Run site parser tests and verify GREEN**

Run: `python -m pytest tests/test_proxy_site_checks.py -q`

Expected: all tests pass.

---

### Task 5: CLI orchestration, safe report writing, and exit codes

**Files:**
- Create: `benchmarks/proxy_quality.py`
- Create: `tests/test_proxy_quality_cli.py`
- Modify: `benchmarks/__init__.py`

**Interfaces:**
- Consumes all Task 1-4 interfaces.
- Produces `run_proxy_quality_scan(proxy: str, output_dir: Path, *, browser_checks: bool, ipinfo_token: str | None) -> dict[str, object]`.
- Produces CLI entry point `python -m benchmarks.proxy_quality`.

- [ ] **Step 1: Write failing CLI tests**

Test with monkeypatched adapters:

- Missing `CLOAK_TEST_PROXY` exits 2 without printing environment contents.
- Connectivity failure exits 3.
- A blocked reputation remains exit 0 and appears in JSON.
- `PROXY_QUALITY_SKIP_BROWSER=1` yields site state `skipped` and summary `unknown` unless other evidence makes it questionable/blocked.
- The output directory is timestamped and contains `report.json` plus `sources.json`.
- A nested credential makes `assert_no_secrets` abort before `Path.replace()`.

- [ ] **Step 2: Run CLI tests and verify RED**

Run: `python -m pytest tests/test_proxy_quality_cli.py -q`

Expected: import failure because the CLI module does not exist.

- [ ] **Step 3: Implement orchestration and atomic serialization**

Execution order:

1. Read and validate environment.
2. Resolve exit IP and latency.
3. Collect intelligence with per-source error isolation.
4. Classify network.
5. Run or skip browser checks.
6. Aggregate summary.
7. Build a `secrets` set from parsed username/password and raw proxy.
8. Run `assert_no_secrets()` against report and console payload.
9. Write JSON to `.tmp`, flush, then replace the final path.
10. Print only the redacted endpoint, summary, and artifact path.

Catch only known configuration, connectivity, and artifact exceptions at the CLI boundary and map them to exit codes 2, 3, and 4. Unexpected exceptions must produce a credential-scrubbed error message and nonzero status.

- [ ] **Step 4: Run CLI tests and verify GREEN**

Run: `python -m pytest tests/test_proxy_quality_cli.py -q`

Expected: all tests pass.

- [ ] **Step 5: Run all deterministic scanner tests**

Run:

```powershell
python -m pytest `
  tests/test_proxy_quality_models.py `
  tests/test_proxy_intelligence.py `
  tests/test_proxy_site_checks.py `
  tests/test_proxy_quality_cli.py `
  tests/test_fingerprint_scanners.py -q
```

Expected: all tests pass with no network access.

---

### Task 6: Documentation and controlled live verification

**Files:**
- Modify: `README.md`
- Modify: `docs/CODEBASE_FUNCTIONALITY.md`
- Generate: `benchmarks/results/proxy-quality/<timestamp>/report.json`

**Interfaces:**
- Consumes the CLI from Task 5.
- Produces documented commands and evidence for the current proxy.

- [ ] **Step 1: Document installation and no-browser mode**

Add:

```powershell
python -m pip install -e ".[geoip]"
$env:CLOAK_TEST_PROXY = "socks5://user:password@host:port"
python -m benchmarks.proxy_quality

# Intelligence/connectivity only; no Google or Cloudflare requests
$env:PROXY_QUALITY_SKIP_BROWSER = "1"
python -m benchmarks.proxy_quality
```

Explain `type`, `type_confidence`, `reputation`, `suitable_for_protected_sites`, source licenses, caching, request limits, and the distinction between `clean_observed` and universally clean.

- [ ] **Step 2: Run fresh compilation and deterministic tests**

Run:

```powershell
python -m py_compile benchmarks/proxy_quality_models.py benchmarks/proxy_intelligence.py benchmarks/proxy_site_checks.py benchmarks/proxy_quality.py
python -m pytest tests/test_proxy_quality_models.py tests/test_proxy_intelligence.py tests/test_proxy_site_checks.py tests/test_proxy_quality_cli.py tests/test_fingerprint_scanners.py -q
```

Expected: exit code 0 and all tests pass.

- [ ] **Step 3: Run one full live scan of the supplied proxy**

Set `CLOAK_TEST_PROXY` only in the process environment, then run:

```powershell
python -m benchmarks.proxy_quality --output-dir benchmarks/results/proxy-quality
```

Expected: exit code 0 for a completed scan even if the reputation is `blocked`; report reproduces the observed Google CAPTCHA without attempting to solve it.

- [ ] **Step 3a: Run one separate direct-network control**

Unset `CLOAK_TEST_PROXY`, then run:

```powershell
python -m benchmarks.proxy_quality --direct-control --output-dir benchmarks/results/proxy-quality
```

Expected: a separate `direct-control/<timestamp>/direct-control.json` and optional `google.png`. It records one Google navigation, reads no proxy value, and is explicitly excluded from proxy report evidence.

- [ ] **Step 4: Validate artifact privacy**

Search all source, docs, tests, and generated JSON for the real username, password, and raw proxy string. The command must return no matches. Also inspect `report.json` to confirm it contains no token value, cookie, HTML body, or browser storage.

- [ ] **Step 5: Re-run core CloakBrowser regression tests**

Run:

```powershell
python -m pytest tests/test_fingerprint_preset.py tests/test_session.py tests/test_launch.py tests/test_persistent_context.py -q
```

Expected: all tests pass.

## Final verification checklist

- [ ] Every new deterministic function was introduced through a failing test.
- [ ] All deterministic tests pass without network access.
- [ ] The browser stage sends no more than one initial request per protected site.
- [ ] The current proxy report classifies type with explicit evidence/confidence.
- [ ] The current proxy's Google CAPTCHA outcome is reproduced.
- [ ] A skipped or unavailable browser stage cannot produce `clean_observed`.
- [ ] No credential, token, cookie, HTML, or storage state appears in artifacts.
- [ ] A separate direct-network Google control is recorded and cannot affect the proxy report.
- [ ] Documentation attributes upstream datasets and states their limitations.
