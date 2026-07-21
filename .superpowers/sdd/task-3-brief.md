### Task 3: Trusted intelligence adapters

Modify `benchmarks/proxy_intelligence.py` and `tests/test_proxy_intelligence.py`; create only sanitized documentation-range fixtures under `tests/fixtures/proxy_quality/`.

Produce exact interfaces:

- `parse_network_list(path: Path, *, minimum_score: int | None = None) -> list[ipaddress._BaseNetwork]`.
- `match_networks(ip: str, networks: list[ipaddress._BaseNetwork]) -> list[str]`.
- `lookup_sapics_asn(ip: str, path: Path) -> dict[str, object] | None`.
- `lookup_ipinfo(ip: str, token: str | None) -> dict[str, object] | None`.
- `collect_intelligence(ip: str, cache: DatasetCache, token: str | None) -> dict[str, object]`.

Fixtures must use only `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, or documentation IPv6 ranges. Tests must prove comments/blank lines are ignored, IPsum scores below 3 are excluded, IPv4/IPv6 CIDRs match, the most specific sapics ASN range wins, missing IPinfo token makes no network call, and one failed source remains `unavailable` without discarding other sources.

Pinned sources:

- `https://raw.githubusercontent.com/stamparm/ipsum/master/ipsum.txt`
- `https://raw.githubusercontent.com/firehol/blocklist-ipsets/master/firehol_level1.netset`
- `https://raw.githubusercontent.com/firehol/blocklist-ipsets/master/firehol_level2.netset`
- sapics `@ip-location-db/iptoasn-asn` via jsDelivr: resolve current version from package metadata, record it, then select IPv4/IPv6 CSV assets from the package file list rather than guessing names.
- Optional IPinfo endpoint `https://api.ipinfo.io/lite/{ip}?token=...`; never serialize the token or request URL. Preserve structured fields such as `is_mobile`, `is_hosting`, privacy, carrier, ASN/name/type when returned.

Each source result shape:

```python
{
  "source": "ipsum",
  "status": "available",
  "retrieved_at": "2026-07-21T00:00:00Z",
  "sha256": "...",
  "matches": ["203.0.113.0/24"],
}
```

Add constants for repository, dataset URL, license/attribution URL. Every enabled source must appear in the manifest even when unavailable. Do not combine broader FireHOL lists beyond levels 1 and 2. IPsum minimum score is 3.

Global constraints:

- Source failures are isolated and reported as unavailable.
- Credentials/API tokens never appear in logs, exceptions, metadata, or reports.
- Tests require no network.
- Follow TDD with RED/GREEN evidence.
- Do not implement browser checks or CLI orchestration.
- This is not Git; do not commit.

Verification: `python -m pytest tests/test_proxy_intelligence.py -q` and `python -m py_compile benchmarks/proxy_intelligence.py`.

Write full report to `.superpowers/sdd/task-3-report.md`.
