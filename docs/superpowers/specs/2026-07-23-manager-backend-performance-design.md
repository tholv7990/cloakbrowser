# Manager Backend Performance Design

## Goal

Keep the local FastAPI/SQLite manager responsive at 1,000 profiles, with up to
100 historical runtime sessions per profile, 1,000 proxies, and 100 media
assets. The optimization must preserve API behavior, authentication,
transactional safety, credential isolation, and SQLite durability.

## Evidence and Current Bottlenecks

A synthetic in-memory SQLite sample showed:

- Listing 100 proxies used 101 SQL statements and took about 21 ms.
- Listing 50 media assets used 51 SQL statements and took about 13 ms.
- Listing a 100-profile page used four statements, but eagerly loaded all
  runtime history for those profiles merely to derive the current runtime state.
- Session history and resource snapshots look up profile names one row at a
  time.
- Each connected WebSocket queries and materializes the complete runtime
  history approximately 20 times per second even when no runtime changed.
- SQLite foreign keys do not automatically create the reverse lookup indexes
  required by several assignment and history queries.

These numbers are development-machine observations, not production service
level guarantees. Regression tests will enforce bounded query counts and
bounded row loading; a repeatable benchmark will report timings without using
fragile timing assertions in the normal test suite.

## Selected Approach

Use targeted indexing, set-based SQL, and selective caching.

Do not add a general application response cache. Profiles, proxies, media
assignments, and runtime state are mutable, and broad caching would introduce
stale reads and complicated invalidation. Retain the existing short
resource-monitor snapshot cache and cache only the last WebSocket runtime
snapshot/change marker per connection.

Do not denormalize runtime state or assignment counts into stored columns.
Those values can be derived efficiently and denormalization would create new
consistency failure modes.

## Query Design

### Profiles

Profile list and detail queries must not eager-load historical
`RuntimeSession` objects. Runtime state will be derived from the active runtime
rows only. Because the database enforces at most one active runtime per
profile, a filtered relation or set-based active-state lookup is bounded by the
number of returned profiles rather than total history.

Tags remain loaded with `selectinload`, preserving current response ordering
and shape. Pagination, filters, sorting, and the count query remain
semantically unchanged.

### Proxies and Media

Proxy assignment counts and media assignment counts will use grouped aggregate
queries. A list operation must use a constant number of SQL statements,
independent of the number of returned rows.

Single-item create, update, and assignment responses may reuse the same
aggregate helper or perform one targeted count. Credential reads remain in the
secure `CredentialStore`; no cache or query optimization may expose or persist
secrets.

### Resource Monitor and Session History

Profile names will be loaded with SQL joins instead of one `Session.get()` per
runtime. The resource monitor continues to cache its complete process snapshot
for less than one polling period. Cached data must not contain credentials or
mutable ORM objects.

Session history remains limited by the requested API limit. Duration, startup
time, and exit-reason calculations remain unchanged.

### Runtime WebSocket

Idle WebSocket clients must not repeatedly fetch and serialize the full
runtime-history table.

Each connection will:

1. Poll a lightweight runtime change marker at a bounded interval.
2. Load the bounded current runtime payload only when the marker changes.
3. Preserve the existing initial snapshot and state-change delivery behavior.
4. Continue forwarding diagnostic events immediately.

Historical stopped sessions are available through the session-history API and
do not belong in every live runtime snapshot. The live snapshot will contain
the current/latest runtime information needed by frontend runtime-state
reconciliation. The exact payload choice must be verified against the React
realtime reducer before implementation.

The target idle interval is 250 ms unless contract inspection demonstrates a
stricter existing requirement. This caps database polling at four lightweight
checks per second per client instead of approximately twenty full-history
loads.

## Database Indexes

Add a new Alembic migration and matching SQLAlchemy metadata declarations for:

- `profiles(proxy_id)` for proxy assignment counts and foreign-key checks.
- `runtime_sessions(profile_id, created_at)` for profile history and active
  runtime lookup.
- `runtime_sessions(created_at, id)` for recent-session ordering.
- `profile_media_assets(media_asset_id, profile_id)` for reverse media
  assignment counts and deletion.
- A partial or composite active-profile listing index based on measured
  `EXPLAIN QUERY PLAN` output, only if SQLite uses it for the actual list
  query.

Additional indexes will be added only when an actual query plan demonstrates
their use. Avoid speculative indexes because every index increases write cost
and database size.

The migration must apply to existing databases and downgrade cleanly.
`Base.metadata.create_all()` remains insufficient for upgrading existing
installations; tests must exercise the Alembic migration path.

## SQLite Configuration

Keep:

- WAL journal mode.
- Foreign-key enforcement.
- The current busy timeout.
- Current durability/synchronous behavior.

Do not enable `synchronous=OFF`, unbounded memory mapping, unsafe shared
connections, or a process-global SQLAlchemy session.

Connection pooling changes are out of scope unless measurements show connection
setup to be material after query improvements.

## Testing and Benchmarks

Tests will be written before each production change.

Required regression coverage:

- Proxy and media lists execute a constant number of SQL statements.
- A profile page does not materialize historical runtime sessions.
- Runtime state remains correct for active and stopped profiles.
- Resource and session history queries remain constant-query as profile count
  grows.
- WebSocket idle polling does not repeatedly load full runtime rows.
- WebSocket initial and changed snapshots retain their frontend contract.
- New indexes exist after migration, are absent after downgrade, and are used
  by the intended SQLite query plans where practical.
- Existing manager security, API-contract, migration, and runtime tests remain
  green.

A standalone benchmark test or script will seed the target scale:

- 1,000 profiles.
- 100 runtime sessions per profile.
- 1,000 proxies.
- 100 media assets.

It will report statement counts, rows/materialized objects, and wall-clock
timings. Normal CI assertions will enforce query/row bounds rather than tight
wall-clock thresholds to remain deterministic across machines.

## Success Criteria

- Proxy and media list SQL statement counts are constant with collection size.
- Profile pages load only the runtime rows required to derive current state.
- Session/resource profile-name loading is set-based.
- Idle WebSocket clients never materialize full runtime history on each poll.
- The target-scale benchmark completes without unbounded memory growth.
- Public API schemas and frontend behavior remain unchanged.
- No secret handling, authentication, backup safety, or runtime binary
  verification behavior changes.

## Out of Scope

- Replacing SQLite with PostgreSQL.
- Adding Redis or another external cache.
- Denormalizing counters or runtime state.
- Frontend performance work.
- Browser-engine launch or fingerprint performance.
- Changing runtime, profile, proxy, or media API response schemas.
