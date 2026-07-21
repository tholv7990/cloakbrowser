# Task 2: Connectivity and cache primitives report

## Scope

Created only the Task 2 implementation and deterministic tests:

- `benchmarks/proxy_intelligence.py`
- `tests/test_proxy_intelligence.py`

The implementation imports and uses `redact_proxy` from
`benchmarks.proxy_quality_models`.  It provides proxy URL validation, exit-IP
resolution through alternating echo endpoints, credential-safe connectivity
errors, SHA-256 hashing, and an atomic file cache with sanitized metadata.

## TDD evidence

### RED: initial interfaces

Command:

```powershell
python -m pytest tests/test_proxy_intelligence.py -q
```

Output (exit code 1):

```text
ImportError while importing test module '...tests\\test_proxy_intelligence.py'.
E   ModuleNotFoundError: No module named 'benchmarks.proxy_intelligence'
1 error in 0.14s
```

This was the expected missing-module failure before production code existed.

### GREEN: initial implementation

Command:

```powershell
python -m pytest tests/test_proxy_intelligence.py -q
```

Output (exit code 0):

```text
...........                                                              [100%]
11 passed in 1.47s
```

### RED/GREEN: credential-safe cache failure

A self-review test made the fake downloader raise an error containing
`https://user:password@example.invalid/ipsum.txt`.  It proved the cache was
initially propagating the unsafe exception text.

Command:

```powershell
python -m pytest tests/test_proxy_intelligence.py -q
```

RED output (exit code 1):

```text
FAILED tests/test_proxy_intelligence.py::test_cache_removes_temporary_file_after_failure_and_keeps_existing_file
AssertionError: assert 'user:password' not in 'download failed for https://user:password@example.invalid/ipsum.txt'
1 failed, 10 passed in 1.41s
```

The cache now replaces download failures with the credential-free message
`Dataset download failed` while still removing temporary files and preserving
the prior cache entry.

GREEN and compile command:

```powershell
python -m pytest tests/test_proxy_intelligence.py -q; if ($LASTEXITCODE -eq 0) { python -m py_compile benchmarks/proxy_intelligence.py }
```

Output (exit code 0):

```text
...........                                                              [100%]
11 passed in 1.30s
```

## Final verification

Command:

```powershell
python -m pytest tests/test_proxy_quality_models.py tests/test_proxy_intelligence.py -q; if ($LASTEXITCODE -eq 0) { python -m py_compile benchmarks/proxy_intelligence.py }
```

Output (exit code 0):

```text
....................                                                     [100%]
20 passed in 1.28s
```

## Self-review

- `resolve_exit_ip` validates inputs without including the raw proxy in errors,
  constructs `httpx.Client(proxy=proxy, timeout=10.0, follow_redirects=False)`,
  alternates the two required endpoints, normalizes values with
  `ipaddress.ip_address`, requires two successes, and exposes agreement and
  successful-call latency values.
- SOCKS transport initialization errors explain the required
  `pip install -e ".[geoip]"` command while redacting URI credentials.
- Cache metadata contains only a credential-stripped URL, UTC retrieval time,
  SHA-256, and byte count.  The downloaded `.tmp` is hashed before replacing
  the target; failure cleanup removes temporary files and leaves an older cache
  entry intact.
- All Task 2 tests use monkeypatch/fakes and make no network request.

## Concerns

None for Task 2.  Test values use documentation-only IP ranges and synthetic
credentials.

## Reviewer fix pass

The following review findings were addressed only in Task 2 files:

- Removed `socks4` and `socks4a` from accepted proxy schemes; httpx supports
  only the SOCKS5 variants used by this scanner.
- Client-construction failures are now converted to `ProxyConnectivityError`
  with exception chaining suppressed.  SOCKS failures retain the required
  `pip install -e ".[geoip]"` guidance but only show a redacted proxy.
- Added a test that renders the complete exception traceback and confirms the
  raw synthetic username and password never appear.
- Made cache publication transactional.  Existing data and metadata are moved
  to sibling backups before either new file is published, and are restored if
  either replacement fails.  The new regression test fails the metadata
  replacement after the data replacement and verifies both older files remain
  unchanged.
- Preserved brackets around IPv6 hosts when reconstructing credential-free
  metadata URLs, with coverage for an IPv6 host and explicit port.
- Removed the no-longer-needed `tests/fixtures/proxy_quality/ipify.json`.

### RED: reviewer regression tests

Command:

```powershell
python -m pytest tests/test_proxy_intelligence.py -q
```

Output (exit code 1):

```text
.FF...F......F.F                                                         [100%]
5 failed, 11 passed in 1.50s
```

The failures demonstrated all requested defects: accepted SOCKS4 schemes,
credential-bearing chained SOCKS initialization errors, unbracketed IPv6
metadata URLs, and non-transactional cache replacement.

During the first GREEN implementation, the pre-download failure cleanup test
found one additional rollback edge case (it removed the existing cache before
backups had been created):

```text
1 failed, 15 passed in 1.51s
```

Rollback cleanup was then limited to paths that had actually been replaced.

### GREEN: final reviewer verification

Command:

```powershell
python -m pytest tests/test_proxy_intelligence.py -q; if ($LASTEXITCODE -eq 0) { python -m py_compile benchmarks/proxy_intelligence.py }
```

Output (exit code 0):

```text
................                                                         [100%]
16 passed in 1.45s
```

`python -m py_compile benchmarks/proxy_intelligence.py` completed with exit
code 0 and emitted no output.

## Post-commit cleanup fix

Backup deletion is now explicitly best-effort after both new cache files have
been published.  A cleanup failure leaves the complete new data/metadata pair
in place and may retain an old backup for a later cleanup; it cannot enter the
rollback path or delete the newly published files.

### RED: backup cleanup regression

Command:

```powershell
python -m pytest tests/test_proxy_intelligence.py -q
```

Output (exit code 1):

```text
................F                                                        [100%]
1 failed, 16 passed in 1.43s
```

The new test simulated failure while removing the metadata backup after the
new data and metadata files had been published.  The prior code entered its
rollback path and raised `Dataset download failed`.

### GREEN: final verification

Command:

```powershell
python -m pytest tests/test_proxy_intelligence.py -q; if ($LASTEXITCODE -eq 0) { python -m py_compile benchmarks/proxy_intelligence.py }
```

Output (exit code 0):

```text
.................                                                        [100%]
17 passed in 1.47s
```

`python -m py_compile benchmarks/proxy_intelligence.py` again completed with
exit code 0 and emitted no output.
