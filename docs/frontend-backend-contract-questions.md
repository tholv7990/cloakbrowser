# Frontend ↔ Backend contract notes

The frontend (`manager/frontend/`) is reconciled against the **canonical
`manager_backend/openapi.json`** (spec §16) plus the updated design spec. Most
earlier open questions are now resolved by the shipped backend. This file records
what is confirmed, what the frontend assumes, and which endpoints are not built
yet (so the frontend still mocks them).

## Resolved against the OpenAPI

- **Auth (§3).** Email+password owner account with an HttpOnly, SameSite=Strict
  session cookie and a session-bound `X-CSRF-Token` on mutations. The per-install
  token is never exposed to JS. Endpoints: `GET /auth/status`, `POST /auth/setup`,
  `POST /auth/login`, `GET /auth/session`, `POST /auth/logout`, `POST /auth/lock`,
  `POST /auth/change-password`. `OwnerSessionRead` is `{ email, csrf_token }`
  (sessions persist until logout — no expiry fields). Frontend: `src/api/http.ts`
  sends `credentials: 'include'` + CSRF header; `src/features/auth/`.
- **Profiles.** `ProfileRead`/`ProfileCreate`/`ProfilePatch` with grouped
  `location`/`window`/`behavior` (`extra="forbid"`), `tag_ids`,
  `workflow_status_id`, `runtime_state` enum (`stopped|starting|running|stopping|crashed`),
  `startup_urls[]`, `fingerprint_revision`/`fingerprint_config_hash`,
  `browser_version_mode`, `user_agent_mode`. No `windows_persona`. Types mirror
  the schema exactly (`src/types/api.ts`).
- **PATCH replaces the whole profile** (`ProfilePatch` carries every field), so
  the editor and row actions re-send the full object (`readToWrite` in
  `src/features/profiles/view.ts`).
- **Pagination** uses `{ items, total, page, page_size, pages }` (`pages`, not
  `total_pages`). **Bulk** is `{ action: trash|restore|pin|unpin|move_folder|set_status, ids, folder_id?, workflow_status_id? } → { updated_ids, count }`.
- **Catalog.** `FolderRead` has no profile/running counts; `TagRead`/`WorkflowStatusRead`
  as documented. `GET /profiles` filters: `query, folder_id, tag_id, workflow_status_id, pinned, sort, page, page_size` (default sort `-updated_at`). No `runtime_state`/`proxy_reputation` server filters — those UI filters were removed.
- **`GET /app/bootstrap` is minimal**: `{ api_version, platform, owner_email, capabilities }`
  where `capabilities` flags which features exist. It does **not** aggregate the
  catalog. The frontend composes folders/tags/statuses/version from their
  dedicated endpoints (`src/hooks/useAppData.ts`).

## Not implemented in the backend yet (frontend mocks these)

The backend is a foundation; these endpoints are absent from the OpenAPI, so the
frontend serves them from the mock adapter and will switch to real when they
ship. `capabilities.*` flags let the UI detect availability.

- **Diagnostics** — `/diagnostics*`, pixelscan, direct-Google control (flag:
  `fingerprint_diagnostics`).
- **Runtime extras** — `/profiles/{id}/logs`, `/export`, `/profiles/import`,
  `/cookies/import`, `/cookies/export` (flag: `browser_runtime`).
- **Settings** — `/settings` (no schema yet); the Settings screen is mock-backed.
- **Extensions list** — no endpoint; the wizard Extensions step is informational
  and `extension_ids` is not part of `ProfileCreate` (do not send it).
- **Running-session count** and **profile root path** are not exposed; the header
  running count defaults to 0 and the "copy profile path" action uses `<id>`
  until a source exists.

## Frontend assumptions (small, isolated)

- `POST /proxies/parse` body `{ raw }`; `POST /folders/reorder` body `{ ids }`;
  `POST /diagnostics/pixelscan` body `{ profile_id }` — for the not-yet-built
  endpoints above.
- "Open profile folder" copies the profile path (no desktop-bridge endpoint);
  "Refresh GeoIP" runs the assigned proxy's quick-test.
- Proxy report `screenshot_path`/`report_path` render as text until a static
  reports route exists.

## Requests to the backend — table-editing iteration (2026-07-21)

The profiles table now supports inline editing (name, notes, tags) and an
in-table proxy assign/add/edit popup. This raises the priority of a few backend
items. **For the backend owner (Codex):**

1. **Proxy management is implemented.** The in-table popup uses the real
   list/create/edit/parse/quick-test/quality-test/report routes. Creating inside
   a profile saves the reusable proxy first; confirming Assign writes its ID
   through the profile PATCH.
2. **Consider a true partial PATCH for profiles.** `ProfilePatch` currently
   carries every field (with `ProfileCreate` defaults), so a partial body would
   reset omitted fields. To make one field editable, the frontend re-sends the
   **whole** profile object with the field changed (`readToWrite` +
   `useUpdateProfileInline`). That works, but a real partial update (fields
   optional with an "unset" sentinel, only provided fields changed) would be
   safer for concurrent edits and lighter on the wire. Not blocking — just a
   quality/safety improvement.
3. **Tag create-and-apply** uses the existing `POST /tags` (`{ name, color? }`).
   The frontend sends a color from a small palette; please confirm the server
   default/uniqueness (we dedupe by name client-side too). `POST /workflow-statuses`
   is available for the same pattern when the UI needs it.
4. Still deferred and mock-backed (unchanged): diagnostics, settings, profile
   logs/export/import, cookies import/export, extensions list, running-session
   count, and profile root path.
