# CloakBrowser Windows Profile Manager — Frontend

The React dashboard for the CloakBrowser Windows Profile Manager. It is the
frontend half of the contract in
[`docs/superpowers/specs/2026-07-21-windows-profile-manager-design.md`](../../docs/superpowers/specs/2026-07-21-windows-profile-manager-design.md);
the FastAPI/SQLite backend is built separately and serves this app's compiled
`dist/` in production.

Original CloakBrowser visual system — no third-party UI kit, no third-party
branding or palettes.

## Stack

React 19 · TypeScript · Vite · Tailwind CSS · TanStack Table · TanStack Query ·
React Hook Form · Zod · Lucide · native WebSocket · Vitest + React Testing
Library.

## Getting started

```bash
cd manager/frontend
npm install
cp .env.example .env.local   # optional; defaults to mock mode
npm run dev                  # http://localhost:5273
```

With no `.env.local`, the app runs in **mock mode** — a full in-browser backend
(`src/mocks/`) with realistic fixtures, so every screen works without the Python
server running.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Vite dev server |
| `npm run build` | Production build to `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run test` | Vitest (run once) |
| `npm run test:watch` | Vitest watch mode |
| `npm run format` / `format:check` | Prettier write / check |

## Environment variables

Configured via `.env.local` (see `.env.example`). All are optional in mock mode.

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_MODE` | `mock` | `mock` uses the in-browser fixtures; `real` talks to the backend. |
| `VITE_API_BASE_URL` | `http://127.0.0.1:8799/api/v1` | REST base URL, including the `/api/v1` prefix. Loopback only. |
| `VITE_WS_URL` | derived from API base (`http→ws` + `/events`) | Runtime-events WebSocket endpoint. |

**Switching to the real backend:** set `VITE_API_MODE=real` and point
`VITE_API_BASE_URL` at the running manager. Nothing else changes — `mockApi` and
`realApi` implement the same `ApiAdapter` (`src/api/adapter.ts`), selected in
`src/api/index.ts`. The backend currently implements auth, profiles, folders,
tags, workflow-statuses, reusable proxies, proxy quick tests, and proxy quality
reports. Diagnostics and settings are still served by the mock (see
`docs/frontend-backend-contract-questions.md`).

## Authentication

The manager is protected by a single **local owner account** (email + password).
The session lives in an HttpOnly, SameSite=Strict cookie the browser sends
automatically; mutations carry a session-bound `X-CSRF-Token` header (from
`GET /auth/session`). JavaScript never sees the session token. First run shows a
setup screen; afterwards a login screen. Sessions persist until you sign out
(header → sign-out icon).

In **mock mode** you start already signed in so the dashboard is immediately
usable; use the sign-out control to exercise the login/setup screens (the mock
then requires signing back in).

## Languages

English and Vietnamese, toggled from the header (**EN / VI**). The preference is
persisted. Add strings in `src/i18n/en.ts` + `src/i18n/vi.ts` and read them with
`useT()`.

## Architecture

Feature-oriented folders under `src/`:

- `api/` — one typed HTTP client (`http.ts`), the `ApiAdapter` interface, and the
  `real`/`mock`-interchangeable implementations. Everything imports `api` from
  `api/index.ts`; nothing imports a concrete adapter.
- `realtime/` — a single WebSocket connection (`RealtimeClient`) and a provider
  that maps events onto the TanStack Query cache. In mock mode it bridges to the
  in-memory event emitter, so realtime works identically offline.
- `types/` — hand-maintained request/response (`api.ts`) and event (`events.ts`)
  types matching the spec. `schemas/` — Zod for form validation + payload mapping.
- `features/{profiles,profile-editor,proxies,folders,diagnostics,settings}/` —
  each screen with its own data hooks and components.
- `components/ui/` — the headless, accessible primitive kit (Button, Menu, Modal,
  Drawer, Popover, Toast, form fields, states). `components/domain/` — status
  badges. `components/FingerprintGlyph.tsx` — the per-identity signature mark.
- `app/` — providers, router, query client, theme, and the local UI-prefs store
  (Zustand, persisted). Server state lives only in TanStack Query.
- `mocks/` — fixtures + the mock backend. `test/` — Vitest setup + a
  `renderWithProviders` helper.

### Notes on behavior

- **Server state is never duplicated** into global state. TanStack Query owns it;
  Zustand holds only local UI preferences (theme, sidebar, table columns, rows
  per page).
- **Optimistic updates only where safe** — pin/unpin, the immediate
  start→starting / stop→stopping transition, and trash removal. Terminal runtime
  state comes from the backend via events (the backend is authoritative).
- **Secrets never surface** — proxy password fields are write-only (a blank
  password on edit keeps the stored one), responses carry only `has_password` and
  masked endpoints, and the UI never renders passwords, tokens, cookies, or auth
  headers.
- **Accessibility** — dialogs/drawers trap focus and close on Escape; menus have
  full keyboard navigation; icon-only controls carry labels; keyboard focus is
  always visible; `prefers-reduced-motion` is respected.

Open questions where the spec leaves a payload unspecified are tracked in
[`docs/frontend-backend-contract-questions.md`](../../docs/frontend-backend-contract-questions.md).
