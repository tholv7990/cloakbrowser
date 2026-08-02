# Unified Proxy Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace divergent proxy forms with one drawer-based editor whose current values are always tested and whose API never returns stored passwords.

**Architecture:** `ProxyEditorDrawer` owns proxy form state and create/update/test orchestration for every entry point. Profile forms render only the selected-proxy summary and open the drawer to create, edit, assign, or remove a proxy. Backend read contracts expose `has_password` but never the password value; empty edit credentials preserve the stored secret unless `clear_credentials` is explicitly requested.

**Tech Stack:** React 18, TypeScript, React Hook Form, Zod, TanStack Query, Vitest/Testing Library, FastAPI, Pydantic, SQLAlchemy, pytest.

## Global Constraints

- Use `ProxyEditorDrawer` as the only interactive proxy editor.
- Quick Test must test the current validated form values, including dirty edits to an existing proxy.
- Full Quality Test must persist dirty values before starting the ID-keyed job.
- Stored proxy passwords must never be returned to or rendered by the frontend.
- Empty edit credentials preserve existing stored credentials; replacement and explicit clearing remain supported.
- Removing an assignment clears `proxy_id` without deleting the reusable proxy.
- Preserve HTTP, HTTPS, SOCKS5, SOCKS5H, and direct modes; never infer protocol from port.
- Do not change proxy provider generation, network-test algorithms, profile launch behavior, or Shop automation.

---

### Task 1: Enforce the write-only proxy credential contract

**Files:**
- Modify: `manager_backend/features/proxies/schemas.py`
- Modify: `manager_backend/features/proxies/service.py`
- Modify: `manager/frontend/src/types/api.ts`
- Modify: `manager/frontend/src/schemas/proxy.ts`
- Test: `tests/manager/test_proxy_api.py`
- Test: `tests/manager/test_proxy_contract.py`
- Test: `manager/frontend/src/schemas/proxy.test.ts`

**Interfaces:**
- Consumes: existing `ProxyWrite`, `ProxyRead`, `create_proxy`, and `update_proxy` contracts.
- Produces: `ProxyRead` with `has_password: bool` and no `password`; update payload semantics where omitted/empty credentials preserve the stored credential and `clear_credentials=true` deletes it.

- [ ] **Step 1: Write failing backend response tests**

Add assertions to create, get, list, and update tests that serialized proxy responses contain no `password` key:

```python
payload = response.json()
assert "password" not in payload
assert payload["has_password"] is True
```

Add a preservation test that updates only the label and verifies `resolve_proxy_url(...)` still contains the original credential, plus replacement and `clear_credentials=True` cases.

- [ ] **Step 2: Run backend tests and verify RED**

Run:

```powershell
python -m pytest tests/manager/test_proxy_api.py tests/manager/test_proxy_contract.py -q
```

Expected: response-shape assertions fail because `ProxyRead` currently includes `password`.

- [ ] **Step 3: Remove password from read models and serializers**

Delete `password` from `ProxyRead`. Ensure the service serializer returns only `username` and `has_password`. Keep password lookup inside `CredentialStore`; do not copy it into a response dictionary.

Normalize update handling so this payload preserves the stored password:

```python
ProxyWrite(
    label="renamed",
    scheme="socks5",
    host="proxy.example",
    port=1080,
    username="user",
    password=None,
    clear_credentials=False,
)
```

`clear_credentials=True` must delete the credential, and a non-empty username/password pair must replace it.

- [ ] **Step 4: Update frontend types and payload conversion**

Remove `password` from the `Proxy` response type. Keep `password` only in `ProxyFormValues` and `ProxyWritePayload`. In `toProxyPayload`, convert an untouched empty password during edit into `password: null` and preserve `clear_credentials: false`; expose an explicit clear action that sets `clear_credentials: true`.

- [ ] **Step 5: Run backend and schema tests GREEN**

Run:

```powershell
python -m pytest tests/manager/test_proxy_api.py tests/manager/test_proxy_contract.py tests/manager/test_proxy_credentials.py -q
cd manager/frontend
npm run test -- --run src/schemas/proxy.test.ts
npm run typecheck
```

Expected: all pass.

- [ ] **Step 6: Commit Task 1**

```powershell
git add manager_backend/features/proxies/schemas.py manager_backend/features/proxies/service.py tests/manager/test_proxy_api.py tests/manager/test_proxy_contract.py manager/frontend/src/types/api.ts manager/frontend/src/schemas/proxy.ts manager/frontend/src/schemas/proxy.test.ts
git commit -m "fix(proxy): keep stored credentials write-only"
```

---

### Task 2: Make the drawer authoritative for current-value testing

**Files:**
- Modify: `manager/frontend/src/features/proxies/ProxyEditorDrawer.tsx`
- Modify: `manager/frontend/src/features/proxies/ProxyEditorDrawer.test.tsx`
- Modify: `manager/frontend/src/features/proxies/api.ts`

**Interfaces:**
- Consumes: `ProxyFormValues`, `toProxyPayload`, `useQuickTestAdhoc`, `useCreateProxy`, `useUpdateProxy`, and `useQualityTest`.
- Produces: one drawer API supporting `proxy`, `onSaved`, `onRemove`, `defaultLabel`, and `submitLabel`, with Quick Test always using current form values and Full Quality Test persisting dirty values first.

- [ ] **Step 1: Write failing Quick Test dirty-value test**

Render the drawer with an existing proxy, change host from `103.82.27.148` to `161.77.1.240`, click Quick Test, and assert:

```tsx
expect(api.quickTestProxyAdhoc).toHaveBeenCalledWith({
  scheme: 'socks5',
  host: '161.77.1.240',
  port: 17735,
  username: '4v7s',
  password: null,
});
expect(api.quickTestProxy).not.toHaveBeenCalled();
```

The test must fail because the current implementation calls the saved-ID endpoint.

- [ ] **Step 2: Write failing password-render test**

Render a saved proxy with `has_password: true` and assert the password input is empty and has the stored-secret placeholder. Ensure no known secret string appears in the document.

- [ ] **Step 3: Write failing Full Quality Test dirty-save test**

Change a saved proxy label/endpoint, click Full Quality Test, and assert `updateProxy` resolves before `qualityTestProxy` receives the same proxy ID. Add a create-mode equivalent asserting create precedes quality test.

- [ ] **Step 4: Run drawer tests RED**

Run:

```powershell
cd manager/frontend
npm run test -- --run src/features/proxies/ProxyEditorDrawer.test.tsx
```

Expected: the three new behaviors fail.

- [ ] **Step 5: Implement current-value Quick Test**

Replace the saved-ID branch in `runQuick` with one ad-hoc call built from `proxyFormSchema.parse(form.getValues())` for both create and edit modes:

```tsx
const values = proxyFormSchema.parse(form.getValues());
setQuickResult(await quickAdhoc.mutateAsync({
  scheme: values.scheme,
  host: values.host,
  port: values.port,
  username: values.username || null,
  password: values.password || null,
}));
```

Keep the displayed result through same-ID query refetches.

- [ ] **Step 6: Implement dirty persistence for quality testing**

Replace `ensureSaved` with `ensureCurrentValuesSaved`. It parses current values, creates when no ID exists, updates when `formState.isDirty` is true, resets from the returned non-secret proxy, then returns the saved proxy.

- [ ] **Step 7: Implement explicit credential clearing**

Render a clear-credentials control only when `current?.has_password` is true. It must set form state so save sends `clear_credentials: true`; typing a replacement password cancels the clear state. Never prefill the password input.

- [ ] **Step 8: Run drawer tests GREEN**

Run:

```powershell
npm run test -- --run src/features/proxies/ProxyEditorDrawer.test.tsx
npm run typecheck
```

Expected: all pass.

- [ ] **Step 9: Commit Task 2**

```powershell
git add manager/frontend/src/features/proxies/ProxyEditorDrawer.tsx manager/frontend/src/features/proxies/ProxyEditorDrawer.test.tsx manager/frontend/src/features/proxies/api.ts
git commit -m "fix(manager-ui): test current proxy editor values"
```

---

### Task 3: Migrate profile creation and advanced editing to the drawer

**Files:**
- Modify: `manager/frontend/src/features/profiles/NewProfileModal.tsx`
- Modify: `manager/frontend/src/features/profiles/NewProfileModal.test.tsx`
- Modify: `manager/frontend/src/features/profile-editor/steps.tsx`
- Modify: `manager/frontend/src/features/profile-editor/ProfileWizardPage.tsx`
- Modify: `manager/frontend/src/features/profile-editor/ProfileWizardPage.test.tsx`
- Modify: `manager/frontend/src/features/profiles/ProfileDialogs.tsx`
- Test: `manager/frontend/src/features/profile-editor/quickAddProxy.test.tsx`

**Interfaces:**
- Consumes: Task 2 `ProxyEditorDrawer` and its `onSaved(proxy)` / `onRemove()` callbacks.
- Produces: profile forms that store only `proxy_id`, show a selected-proxy summary, and open the shared drawer for create/edit/assign/remove.

- [ ] **Step 1: Write failing new-profile integration test**

Open the New Profile modal, activate proxy assignment, open the proxy drawer, enter a SOCKS5 endpoint, save it, and assert the eventual profile create payload contains the returned `proxy_id` and no inline proxy credentials.

- [ ] **Step 2: Write failing advanced-editor integration test**

Open a profile draft with a selected proxy, click Edit proxy, update it through the drawer, and assert the form retains the same proxy ID. Exercise Remove proxy and assert only `proxy_id` becomes null.

- [ ] **Step 3: Run profile integration tests RED**

Run:

```powershell
npm run test -- --run src/features/profiles/NewProfileModal.test.tsx src/features/profile-editor/ProfileWizardPage.test.tsx src/features/profile-editor/quickAddProxy.test.tsx
```

Expected: tests fail because these paths still render `ProxyInlineForm`.

- [ ] **Step 4: Replace NewProfileModal inline proxy state**

Remove `OneProxy`/`ProxyInlineForm` state. Add `selectedProxy: Proxy | null` and drawer-open state. On `onSaved`, set `proxy_id` to the returned ID. On remove, set it to null. Keep the existing profile submission and provider generation behavior unchanged.

- [ ] **Step 5: Replace advanced profile inline proxy UI**

In `steps.tsx`, render a proxy summary with Add/Edit and Remove actions. Hoist drawer state/callbacks through `ProfileWizardPage` so the step does not implement proxy persistence. Update `ProfileDialogs` to use the same callbacks rather than a parallel edit behavior.

- [ ] **Step 6: Run profile integration tests GREEN**

Run:

```powershell
npm run test -- --run src/features/profiles/NewProfileModal.test.tsx src/features/profile-editor/ProfileWizardPage.test.tsx src/features/profile-editor/quickAddProxy.test.tsx
npm run typecheck
```

Expected: all pass.

- [ ] **Step 7: Commit Task 3**

```powershell
git add manager/frontend/src/features/profiles/NewProfileModal.tsx manager/frontend/src/features/profiles/NewProfileModal.test.tsx manager/frontend/src/features/profile-editor/steps.tsx manager/frontend/src/features/profile-editor/ProfileWizardPage.tsx manager/frontend/src/features/profile-editor/ProfileWizardPage.test.tsx manager/frontend/src/features/profile-editor/quickAddProxy.test.tsx manager/frontend/src/features/profiles/ProfileDialogs.tsx
git commit -m "refactor(manager-ui): unify profile proxy editing"
```

---

### Task 4: Retire duplicate UI and run release gates

**Files:**
- Delete: `manager/frontend/src/features/proxies/ProxyInlineForm.tsx`
- Modify: tests/imports that reference `ProxyInlineForm` or `OneProxy`
- Modify: `manager_backend/openapi.json` if the response schema changes

**Interfaces:**
- Consumes: unified drawer and password-safe API from Tasks 1–3.
- Produces: no remaining interactive proxy form outside `ProxyEditorDrawer`.

- [ ] **Step 1: Prove no production references remain**

Run:

```powershell
rg -n "ProxyInlineForm|OneProxy" manager/frontend/src --glob "!**/*.test.*"
```

Expected before deletion: no output. If output remains, migrate that call site before continuing.

- [ ] **Step 2: Delete the retired component and update tests**

Delete `ProxyInlineForm.tsx`. Move any parser/payload assertions into `src/schemas/proxy.test.ts`; keep UI behavior assertions in `ProxyEditorDrawer.test.tsx`.

- [ ] **Step 3: Regenerate OpenAPI**

Run:

```powershell
python -m manager_backend.export_openapi
git diff -- manager_backend/openapi.json
```

Expected: `ProxyRead.password` is removed and no unrelated contract changes appear.

- [ ] **Step 4: Run frontend gates**

Run:

```powershell
cd manager/frontend
npm run typecheck
npm run test
npm run build
```

Expected: all pass.

- [ ] **Step 5: Run backend gates**

Run from repository root:

```powershell
python -m pytest tests/manager -m "not slow" -q
python -m pytest -m "not slow" -q
```

Expected: all feature-related suites pass; report any known unrelated environment failures separately with exact test names.

- [ ] **Step 6: Perform authenticated smoke test**

Against the local manager, log in, create an unsaved SOCKS5 proxy in the drawer, Quick Test it without saving, save it, edit only its label, confirm credentials remain functional, remove its profile assignment, and delete only the test proxy. Confirm no password value appears in the DOM or API response.

- [ ] **Step 7: Commit Task 4**

```powershell
git add manager/frontend/src manager_backend/openapi.json
git commit -m "test(proxy): close unified editor release gates"
```

- [ ] **Step 8: Final review and push only on explicit request**

Run:

```powershell
git status --short
git log --oneline -5
```

Preserve unrelated `.impeccable/hook.cache.json` and `Quantum-Source-Clean-20260721.rar`. Do not stage, delete, inspect, or reference the archive.
