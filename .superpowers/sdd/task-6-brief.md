### Task 6: Frontend — `accountRegister` API surface

**Files:**
- Modify: `manager/frontend/src/types/api.ts`, `api/adapter.ts`, `api/real.ts`, `mocks/mockApi.ts`, `features/account/api.ts`

**Interfaces:**
- Produces: `LicenseStatus.trial_end?: number | null`; `api.accountRegister(payload: EmailPasswordRequest): Promise<LicenseStatus>`; `useAccountRegister()` hook.

- [ ] **Step 1: Add the type field** — in `manager/frontend/src/types/api.ts`, add to `LicenseStatus` (after `grace_deadline`):
```ts
  trial_end?: number | null;
```
(Optional, so existing `LicenseStatus` literals in mocks/tests don't need changes.)

- [ ] **Step 2: Adapter method** — in `manager/frontend/src/api/adapter.ts`, add to the account/license block (after `accountActivate`):
```ts
  accountRegister(payload: EmailPasswordRequest): Promise<LicenseStatus>;
```
(`EmailPasswordRequest` and `LicenseStatus` are already imported there.)

- [ ] **Step 3: Real adapter** — in `manager/frontend/src/api/real.ts`, add (after `accountActivate`):
```ts
  accountRegister: (payload: EmailPasswordRequest) =>
    apiRequest<LicenseStatus>('/account/register', { method: 'POST', body: payload }),
```

- [ ] **Step 4: Mock adapter** — in `manager/frontend/src/mocks/mockApi.ts`, add (after `accountActivate`):
```ts
  async accountRegister(payload: EmailPasswordRequest): Promise<LicenseStatus> {
    await delay(160);
    mockStore.account = { cloud_configured: true, signed_in: true, email: payload.email };
    mockStore.license = {
      state: 'active',
      allowed: true,
      plan: 'trial',
      features: [],
      expires_at: null,
      grace_deadline: null,
      trial_end: null,
      detail: null,
    };
    return mockStore.license;
  },
```

- [ ] **Step 5: Hook** — in `manager/frontend/src/features/account/api.ts`, add:
```ts
export function useAccountRegister() {
  const refresh = useRefreshGate();
  return useMutation({
    mutationFn: (payload: EmailPasswordRequest) => api.accountRegister(payload),
    onSuccess: refresh,
  });
}
```

- [ ] **Step 6: Verify typecheck**

Run: `npm --prefix manager/frontend run typecheck`
Expected: clean (mock + real both satisfy the extended `ApiAdapter`).

- [ ] **Step 7: Commit**

```bash
git add manager/frontend/src/types/api.ts manager/frontend/src/api/adapter.ts manager/frontend/src/api/real.ts manager/frontend/src/mocks/mockApi.ts manager/frontend/src/features/account/api.ts
git commit -m "feat(frontend): accountRegister API surface (real + mock) + useAccountRegister"
```

---

