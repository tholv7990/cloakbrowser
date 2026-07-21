# Task 3 Report: Trusted Intelligence Adapters

## Status

Complete. The trusted intelligence adapters are implemented in `benchmarks/proxy_intelligence.py`, covered by offline tests in `tests/test_proxy_intelligence.py`, and backed only by sanitized documentation-range fixtures.

No Git commands that mutate history were used and no commit was created. The workspace is not a Git repository.

## Files Changed

- Modified `benchmarks/proxy_intelligence.py`
- Modified `tests/test_proxy_intelligence.py`
- Created `tests/fixtures/proxy_quality/ipsum.txt`
- Created `tests/fixtures/proxy_quality/firehol_level1.netset`
- Created `tests/fixtures/proxy_quality/sapics_asn.csv`
- Created `tests/fixtures/proxy_quality/ipinfo.json`
- Created this report at `.superpowers/sdd/task-3-report.md`

No browser checks or CLI orchestration were implemented.

## Interfaces Implemented

- `parse_network_list(path: Path, *, minimum_score: int | None = None) -> list[ipaddress._BaseNetwork]`
- `match_networks(ip: str, networks: list[ipaddress._BaseNetwork]) -> list[str]`
- `lookup_sapics_asn(ip: str, path: Path) -> dict[str, object] | None`
- `lookup_ipinfo(ip: str, token: str | None) -> dict[str, object] | None`
- `collect_intelligence(ip: str, cache: DatasetCache, token: str | None) -> dict[str, object]`

An inspection-based verification confirmed all five signatures exactly.

## Implemented Behavior

### Network lists

- Ignores comments, inline comments, blank lines, and malformed non-network metadata.
- Parses exact IPs and CIDRs through `ipaddress.ip_network(..., strict=False)`.
- Applies the required IPsum minimum score of 3.
- Matches IPv4 and IPv6 only against networks of the same address family.
- Preserves deterministic input order in returned matches.

### sapics ASN adapter

- Parses inclusive IPv4 and IPv6 CSV ranges.
- Selects the narrowest matching range when ranges overlap.
- Returns structured `asn`, `asn_name`, `range_start`, and `range_end` fields.
- Resolves the latest package version from jsDelivr package metadata at runtime.
- Fetches the versioned jsDelivr flat file list and selects the single non-numeric `-ipv4.csv` or `-ipv6.csv` asset for the queried address family; it does not guess the filename.
- Records resolved package version and selected asset in the source manifest.
- Retains a successfully resolved version even if the later CSV fetch is unavailable.

The authoritative metadata was checked on 2026-07-21. It resolved `@ip-location-db/iptoasn-asn` to version `2.3.2026061719`; the package file list contained:

- `/iptoasn-asn-ipv4.csv`
- `/iptoasn-asn-ipv4-num.csv`
- `/iptoasn-asn-ipv6.csv`
- `/iptoasn-asn-ipv6-num.csv`
- `/package.json`
- `/README.md`

`SAPICS_RESOLVED_VERSION` records the version observed during implementation. Runtime collection still resolves the current version from metadata, so the constant is informational provenance rather than a download selector.

### IPinfo adapter

- Returns `None` before any HTTP call when the token is absent.
- Uses the requested IPinfo Lite endpoint when a token is supplied.
- Preserves provider-returned structured fields, including mobile/hosting flags, privacy, carrier, ASN, name, and type.
- Adds `asn_name` and `asn_type` aliases for the provider's `as_name` and `type` fields while preserving the original fields.
- Never places the token or credential-bearing request URL in returned evidence, manifests, or exceptions.
- Sanitizes provider-controlled nested values and keys to prevent a response from echoing the raw or URL-encoded token.
- Converts transport/provider failures to `None` without retaining exception text, because HTTP exception text may contain the credential-bearing request URL.

### Collection and manifest

- Includes all five enabled source entries on every collection attempt: `ipsum`, `firehol_level1`, `firehol_level2`, `sapics`, and `ipinfo`.
- Marks a failed or disabled source `unavailable` without discarding available results from other sources.
- Records source, status, retrieval timestamp, SHA-256, matches, repository URL, dataset URL, and license/attribution URL.
- Reads retrieval timestamp and digest from `DatasetCache` metadata when present; otherwise hashes the local dataset and supplies a UTC timestamp.
- Uses only FireHOL levels 1 and 2.
- Separates IPsum/FireHOL level 1 matches as high-confidence reputation matches and FireHOL level 2 matches as other matches.
- Returns ASN/IPinfo structured evidence as classification signals.
- Does not serialize error messages from failed sources.

## Source Constants

The implementation records repository, dataset, and license/attribution URLs for:

- IPsum: pinned raw `ipsum.txt` URL and repository license.
- FireHOL level 1: pinned raw `firehol_level1.netset` URL.
- FireHOL level 2: pinned raw `firehol_level2.netset` URL.
- FireHOL attribution: the aggregate repository, because incorporated upstream lists have distinct terms rather than one repository-wide license.
- sapics: repository, versioned jsDelivr metadata/file/data templates, and PDDL 1.0 license.
- IPinfo: provider repository/organization, safe endpoint template without a token, and terms URL.

## Fixture Safety

All fixture IP data is restricted to:

- `192.0.2.0/24`
- `198.51.100.0/24`
- `203.0.113.0/24`
- `2001:db8::/32` subranges

The IPinfo fixture uses `example.invalid` for its domain. A verification script parsed every fixture network/range/address and confirmed that all four fixtures stay within documentation space.

## TDD Evidence

### Initial RED

Command:

```text
python -m pytest tests/test_proxy_intelligence.py -q
```

Observed result before production implementation:

```text
7 failed, 17 passed in 1.54s
```

The seven new behavior groups failed for the expected reason: required functions and constants did not yet exist. All 17 pre-existing tests remained green.

### Initial GREEN

After the minimal implementation:

```text
24 passed in 1.30s
```

### Self-review hardening RED

Two additional regression tests were then added for provider-controlled token-bearing JSON keys and retaining a resolved sapics version when the selected asset is unavailable.

```text
2 failed, 23 deselected in 0.22s
```

Both failures matched the intended missing edge behavior.

### Hardening GREEN

```text
2 passed, 23 deselected in 0.13s
25 passed in 1.38s
```

## Final Verification

Fresh commands run after the final code changes:

```text
python -m pytest tests/test_proxy_intelligence.py -q
```

Result:

```text
25 passed in 1.37s
```

```text
python -m py_compile benchmarks/proxy_intelligence.py
```

Result: exit code 0, no output.

Additional read-only verification:

```text
signatures: verified 5/5
fixtures: documentation ranges verified 4/4
```

The tests make no live network requests: network boundaries are replaced only at the lowest external HTTP/cache layer, while parsing, selection, collection, source isolation, hashing, and manifest behavior execute as real code.

## Self-review and Concerns

- Credential handling: no token, actual IPinfo request URL, provider exception text, or failed-source exception is returned or recorded.
- Failure isolation: each local list source, sapics, and IPinfo is independently converted to an explicit manifest status.
- Provenance: every enabled source remains visible when unavailable; sapics records the dynamically resolved package version.
- Scope: only the task-listed implementation, test, fixture, and report paths were edited.
- Maintenance note: `SAPICS_RESOLVED_VERSION` intentionally records the version observed on 2026-07-21 and can become historically stale. Runtime behavior is not stale because it resolves `latest` and the file list for each refreshed metadata generation.
- IPinfo plans expose different field subsets. The adapter preserves arbitrary structured response fields and adds the aliases used by the classifier, so absent plan-specific fields remain absent rather than being inferred.

No unresolved implementation concern blocks Task 3.
