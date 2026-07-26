# Task 6 report: Frontend — `accountRegister` API surface

## Status: DONE

## Commit

`f6858f0` — `feat(frontend): accountRegister API surface (real + mock) + useAccountRegister`
5 files changed, 27 insertions(+), 0 deletions.

## What changed

Transcribed the brief's code verbatim into the real files — the actual file structure matched the
brief exactly (no adaptations needed):

- `manager/frontend/src/types/api.ts` — added `trial_end?: number | null;` to `LicenseStatus`,
  after `grace_deadline` (before `detail`).
- `manager/frontend/src/api/adapter.ts` — added
  `accountRegister(payload: EmailPasswordRequest): Promise<LicenseStatus>;` to the `ApiAdapter`
  interface, right after `accountActivate`. `EmailPasswordRequest` and `LicenseStatus` were already
  imported.
- `manager/frontend/src/api/real.ts` — added `accountRegister` after `accountActivate`, calling
  `apiRequest<LicenseStatus>('/account/register', { method: 'POST', body: payload })`.
- `manager/frontend/src/mocks/mockApi.ts` — added `accountRegister` after `accountActivate`: sets
  `mockStore.account` to signed-in with the payload email, sets `mockStore.license` to an active
  `plan: 'trial'` license with `trial_end: null`, returns it.
- `manager/frontend/src/features/account/api.ts` — added `useAccountRegister()`: a
  `useMutation` wrapping `api.accountRegister(payload)`, with `onSuccess: refresh` where `refresh`
  is the existing `useRefreshGate()` (invalidates both the `LICENSE_KEY` and `ACCOUNT_KEY` react-query
  caches), placed right after `useAccountActivate()`.

## Verification

- `npm --prefix manager/frontend run typecheck` → clean, no errors (confirms both `realApi` and
  `mockApi` satisfy the extended `ApiAdapter` interface).
- `npm --prefix manager/frontend run test` → **26 test files / 115 tests passed**, no regressions.

## Self-review

- Mock return shape: `accountRegister` returns `mockStore.license` populated with all
  `LicenseStatus` fields including the new optional `trial_end: null` — satisfies the type, and
  matches the brief's exact object literal.
- Hook wiring: `useAccountRegister()` uses `useRefreshGate()` (the same shared helper
  `useAccountLogin`/`useAccountActivate`/`useAccountRefresh`/`useAccountLogout` all use), so a
  successful register invalidates both `['license']` and `['account']` query keys — consistent with
  every other account mutation in the file.
- Real adapter: path `/account/register`, method `POST`, body `payload` (an
  `EmailPasswordRequest` — `{ email, password }`), matches the backend route added in Task 5
  (`manager_backend/features/account/routes.py`, `POST /account/register` accepting
  `RegisterRequest` which has the same `email`/`password` shape) and returns `LicenseStatusRead`
  which is what `LicenseStatus` types.
- No new request type was introduced — reused `EmailPasswordRequest` as instructed (its shape,
  `{ email: string; password: string }`, matches the backend's `RegisterRequest`).

## Concerns

None. No adaptations from the brief were needed — the file structure, existing imports, and
placement conventions (`accountRegister` next to `accountActivate` in each file) matched exactly.

## Note on working-tree noise

The working tree contains many unrelated modified/deleted files from other concurrent SDD task
runs (`.superpowers/sdd/task-1..6-*.md` other than this report, `.superpowers/sdd/progress.md`,
`.impeccable/hook.cache.json`, a deleted `Velas Component Colors.dc.html`). None of these were
touched or staged by this task — only the 5 files listed above were staged and committed, per the
brief's instructions.
