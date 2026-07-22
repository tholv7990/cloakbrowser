# Portability Task 4 Report

## Status

Implemented extension persistence, validation, authenticated CRUD/refresh APIs,
profile assignment, migration `0009_extensions`, and the profile-portability export
seam. Runtime loading, frontend work, push operations, source copying, and content
echoing remain outside this task.

## Delivered

- Persisted UUID extension metadata and composite profile assignments with cascade
  cleanup and reversible Alembic migration.
- Validated strict Manifest V2/V3 JSON up to 1 MiB, canonicalized JSON for stable
  SHA-256 hashes, and bounded descriptions and permission summaries.
- Canonicalized local paths and rejected profile-root, temporary, Windows system,
  UNC/mapped-network, symlink, junction, and other reparse paths.
- Added exact-path deduplication (200 for same hash), changed-manifest conflict (409),
  explicit refresh, global enable/disable, metadata-only unregister, list/get, and
  complete transactional profile assignment.
- Exported assigned extension references as deterministic manifest metadata only;
  filesystem paths and source/content are excluded.
- Kept every extension mutation behind the existing authenticated session, allowed
  Origin, and CSRF enforcement, with strict request schemas and safe error bodies.

## TDD and Verification

- Initial focused RED: 3 failures and 9 errors because the extension package,
  routes, and migration did not exist.
- OpenAPI RED: registration advertised 200 rather than the required 201 create
  response before the route declaration was corrected.
- Final focused: `12 passed, 1 skipped`.
- Final full Manager suite: `331 passed, 3 skipped` in 41.38 seconds.
- Migration coverage upgrades through head, inspects both new tables/indexes/foreign
  keys, then downgrades to `0008_runtime_observability` and confirms removal.
- `git diff --check` reports only pre-existing whitespace warnings in SDD brief files
  that are intentionally excluded from this task commit.

The focused skip is the real filesystem-symlink case because this Windows environment
does not grant symlink creation. Reparse-path rejection remains covered by a
non-skipped test, and the implementation checks both symlink state and the Windows
reparse-point attribute for every path component. The full suite's other skips are
pre-existing. The only warning is the existing Starlette/httpx deprecation warning.

## Concerns / Follow-up Boundaries

- The next runtime task must consume only enabled, assigned extension directories;
  this task deliberately does not pass extension flags to browser launch.
- The checked-in generated OpenAPI JSON was not regenerated because it is outside
  the Task 4 file boundary; live `/openapi.json` coverage verifies the contract.
- Pre-existing edits under `.superpowers/sdd/` were preserved and excluded from the
  Task 4 commit, except for this report.

## Review Remediation

A follow-up TDD pass addressed the independent extension review:

- Complete-list assignment now reserves the SQLite writer transaction with
  `BEGIN IMMEDIATE` before reading the profile, validating extension rows, or loading
  the relationship. Concurrent replacements serialize; lock/operational failures map
  to the safe typed `extension_assignment_conflict` 409 response.
- A synchronized stale-read regression reproduced the former union result before the
  fix. A 20-iteration concurrent stress test now proves each committed result is one
  complete requested list, never a union.
- Profile import resolves enabled registered extensions using the exact portable
  identity: canonical manifest hash plus normalized manifest name, version, and
  manifest version. Unique matches are assigned transactionally; missing/disabled
  matches warn as `extension_missing`, while duplicate identities warn as
  `extension_ambiguous`. Neither warning includes manifest values or paths.
- Extension and profile route IDs, plus assignment list entries, must be canonical
  lowercase UUIDv4 strings of exactly 36 characters. Duplicate assignment IDs and
  adversarial oversized values are rejected by strict request validation.
- Registration and refresh use an injected secure filesystem adapter. Windows opens
  directory and manifest handles with reparse-safe flags, holds the directory against
  replacement, verifies file attributes, identity, and final handle paths, and reads
  through the bounded handle. POSIX walks every component with `openat`,
  `O_DIRECTORY`, and `O_NOFOLLOW`, verifies the approved device/inode, then reads the
  regular manifest through its descriptor. No ordinary post-validation path read
  remains.
- Deterministic nonprivileged tests cover adapter-detected swap rejection, ancestor
  reparse detection, exact native-handle reads, and pre-read size rejection. The
  optional real symlink test remains skipped where Windows does not grant link
  creation.

Review verification: focused portability/extension/migration coverage reports
`54 passed, 1 skipped`; the full Manager suite reports `340 passed, 3 skipped`.
The one warning remains the pre-existing Starlette/httpx deprecation warning.
