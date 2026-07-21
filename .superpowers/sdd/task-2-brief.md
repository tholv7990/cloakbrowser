### Task 2: Connectivity and cache primitives

Create `benchmarks/proxy_intelligence.py`, `tests/test_proxy_intelligence.py`, and only the small fixture files needed by these tests.

Consume `redact_proxy` from `benchmarks.proxy_quality_models`.

Produce exact interfaces:

- `validate_proxy_url(value: str) -> None`.
- `resolve_exit_ip(proxy: str, *, attempts: int = 3) -> dict[str, object]`.
- `DatasetCache(root: Path, max_age: timedelta)` with `get(url: str, name: str) -> Path`.
- `sha256_file(path: Path) -> str`.
- A dedicated `ProxyConnectivityError` for insufficient successful echo responses.

Required behaviors and tests:

- Reject malformed proxy URLs and credentials without a host.
- Use monkeypatch/fake HTTP functions so deterministic tests make no network request.
- Query exactly three times by default, alternating `https://api.ipify.org?format=json` and `https://checkip.amazonaws.com/`.
- Normalize all responses with `ipaddress.ip_address`.
- Select the majority IP. `exit_ip_agreement` is true only when all successful responses agree.
- Record three latency values when three calls succeed.
- Require at least two successful responses, otherwise raise `ProxyConnectivityError`.
- Use `httpx.Client(proxy=proxy, timeout=10.0, follow_redirects=False)`.
- Document in an error that SOCKS URLs require `pip install -e ".[geoip]"` when `socksio` is unavailable.

Representative test:

```python
def test_resolve_exit_ip_requires_echo_agreement(monkeypatch):
    responses = iter(["203.0.113.10", "203.0.113.10", "203.0.113.11"])
    monkeypatch.setattr("benchmarks.proxy_intelligence._fetch_echo_ip", lambda *a, **k: next(responses))
    result = resolve_exit_ip("socks5://u:p@proxy.example:1080", attempts=3)
    assert result["exit_ip"] == "203.0.113.10"
    assert result["exit_ip_agreement"] is False
    assert len(result["latency_ms"]) == 3
```

`DatasetCache.get()` must:

1. Reuse a file younger than `max_age`.
2. Download to a sibling `.tmp` file.
3. Hash before `Path.replace()`.
4. Store `<name>.meta.json` with URL, UTC retrieval time, SHA-256, and byte count.
5. Remove a temporary file after failure without deleting an older valid cache entry.

Representative cache test:

```python
def test_cache_reuses_fresh_file(tmp_path, monkeypatch):
    cache = DatasetCache(tmp_path, timedelta(hours=24))
    existing = tmp_path / "ipsum.txt"
    existing.write_text("203.0.113.0/24\t3\n", encoding="utf-8")
    monkeypatch.setattr("benchmarks.proxy_intelligence._download_atomic", lambda *a: (_ for _ in ()).throw(AssertionError()))
    assert cache.get("https://example.invalid/ipsum.txt", "ipsum.txt") == existing
```

Global constraints:

- Credentials must never appear in logs, exceptions, or serialized metadata.
- Public exit IPs may appear.
- Deterministic tests require no internet access.
- Follow TDD and record RED/GREEN evidence.
- Do not implement intelligence-list parsing yet; that is Task 3.
- This is not a Git repository; do not commit.

Verification:

```powershell
python -m pytest tests/test_proxy_intelligence.py -q
python -m py_compile benchmarks/proxy_intelligence.py
```

Write the full report to `.superpowers/sdd/task-2-report.md`.
