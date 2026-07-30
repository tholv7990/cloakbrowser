# Shop-check authenticated smoke test (Task 16)

The final gate before trusting live Shop-check runs. It drives the **real**
pipeline — 711 proxy provisioning, profile creation, headed browser launch,
per-email Shop check, export, cleanup — against a **small set of owned test
accounts**. It is the only validation of `CdpShopSession`'s Shop-specific
locators against the live site, so run it before any larger authorized run.

Harness: [`scripts/shop_check_smoke.py`](../scripts/shop_check_smoke.py).

## Prerequisites (on the Windows box)

- The cloakbrowser binary is cached (auto-downloads on first launch; verify with
  `python -m cloakbrowser info`).
- Network access to shop.app and the 711 proxy egress.
- A working **711 account** and **1–2 owned Shop accounts** you are authorized to
  check. Start with one email.

## Verify the harness first (no creds, no browser)

```powershell
python scripts/shop_check_smoke.py --selftest
```

Expect `RESULT: PASS` with 11 checks. This proves the harness itself is correct
using fakes, so a later real-mode failure points at the environment / live site,
not the harness.

## Run the authenticated smoke test

```powershell
$env:SMOKE_711_USER = "<711 account user>"
$env:SMOKE_711_PASS = "<711 account pass>"
$env:SMOKE_EMAILS   = "me@owned-account.com"      # comma-separated; start with one
$env:SMOKE_REGION   = "US"                          # optional two-letter code
python scripts/shop_check_smoke.py
```

Secrets and accounts come from the environment only — never pass them on the
command line or commit them. The harness prints one PASS/FAIL line per check and
writes a **sanitized** evidence file (timings + counts; no email, address, or
proxy secret) to the data root it reports.

## What each check confirms (maps to the plan)

| Check | Confirms |
|---|---|
| run reached a terminal status | no stuck-`running` (the CRITICAL defect) |
| five-email grouping | `ceil(valid / emails_per_profile)` workers |
| every worker owns a proxy | 711 provisioning + preflight ran per worker |
| unique session directive / fingerprint seed | each profile is a distinct 711 session + fingerprint |
| every assigned email got a terminal result | the real processor checked each email (state reset between the 5 on a shared profile) |
| export wrote results.csv + matched.txt | export produces the deliverable |
| no full email in results.csv | masked-only CSV; plaintext lives only in matched.txt |
| cleanup deleted the owned profiles / left control untouched | cleanup is scoped to run-owned profiles by provenance |

## If a check fails

- **email results are all `navigation_failed` / `unknown`** → `CdpShopSession`'s
  Shop selectors (`get_by_role` email/Continue, `phone_hint`) or the
  `submit()` wait strategy need tuning against the live page. This is the
  expected first place to iterate; the selectors are marked best-effort in
  `browser.py`. Adjust, re-run.
- **run never terminalizes / launch times out** → check the headed browser
  actually started and its `DevToolsActivePort` (CDP endpoint) appeared; the
  readiness wait needs a headed launch with remote-debugging (the manager path).
- **proxy failures** → verify the 711 account and region against the Proxies
  screen quick-test first.

Widen to more owned accounts only after a single-email run passes cleanly.
