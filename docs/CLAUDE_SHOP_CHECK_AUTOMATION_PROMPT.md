# Claude Code Prompt — Build Shop Email Phone-OTP Check Automation

Work in repository:

```text
C:\Users\Admin\Desktop\CloakBrowser
```

Implement the approved Shop email phone-OTP check automation across backend and frontend.
Read these files completely before changing code:

```text
docs/superpowers/specs/2026-07-29-shop-email-phone-check-automation-design.md
docs/superpowers/plans/2026-07-29-shop-email-phone-check-automation.md
docs/backend-contract-automation.md
docs/backend-contract-proxy-providers.md
```

## Product behavior

- Input authorized emails from pasted text or one-per-line UTF-8 text.
- Default five emails per temporary profile; maximum five.
- Create `ceil(email_count / emails_per_profile)` temporary Windows profiles.
- Generate one distinct 711Proxy sticky session per temporary profile.
- Preflight each proxy before profile launch.
- Open `https://shop.app/`, submit each assigned email sequentially, clear Shop origin state
  between emails, and classify the result.
- Export phone-OTP matches to TXT and all outcomes to CSV.
- Extract only visible phone prefix/suffix and conservative country/region mapping.
- After every email is terminal, show completion or completed-with-issues.
- Do not auto-delete profiles. Show a persistent alert and an explicit
  `Delete all run profiles` action.
- Cleanup deletes only immutable profile IDs owned by that run. It must not delete manual
  profiles, profiles from other runs, or proxies.

## Hard security gates

- Authorized accounts only.
- No CAPTCHA bypass and no OTP retrieval, guessing, or submission.
- No raw emails or proxy secrets in logs, exceptions, URLs, query keys, telemetry, or normal
  API responses.
- Full emails live in `CredentialStore`; DB stores refs and SHA-256 fingerprints.
- Proxy credentials remain exclusively in `CredentialStore`.
- Every schema extends `StrictModel` and forbids extras.
- Every mutation keeps existing session/origin/CSRF and maintenance guards.
- Cleanup takes only `run_id`; never accept client profile paths or arbitrary profile IDs.
- Resolve and verify every deletion path remains under the configured profile root.

## Engineering constraints

- Do not restore or repurpose the retired Profile Factory UI/service. Dedicated Shop-check
  tables and services are required.
- Do not change CloakBrowser engine code or weaken binary verification.
- Use a real migration; do not rely on `Base.metadata.create_all()` for existing databases.
- Use test-driven development and small, reviewable commits.
- Use one SQLAlchemy session per background worker.
- Recompute run aggregates from item rows under concurrency.
- All retries must be bounded and idempotent.
- Default tests must use deterministic local HTML fixtures, never real Shop/network calls.
- Preserve unrelated working-tree changes.

## Implementation order

Follow the plan phase by phase. Stop and report for Codex review after:

1. Persistence and schemas.
2. Provisioning/coordinator/recovery.
3. Export and exact-scope cleanup.
4. Frontend plus full verification.

At each checkpoint provide:

- Commit hashes and changed files.
- Tests added and exact command output.
- Known limitations or assumptions.
- Any deviation from the approved design, with justification.

## Required final verification

Backend:

```powershell
python -m manager_backend.export_openapi
pytest tests/manager -m "not slow" -q
```

Frontend, from `manager/frontend`:

```powershell
npm run typecheck
npm run test
npm run build
```

Do not merge or push until Codex completes the final rigorous review. Do not claim completion
if any valid input email remains pending/running/retry-waiting, if cleanup can affect
non-owned profiles, or if any secret/personal-data leak test fails.
