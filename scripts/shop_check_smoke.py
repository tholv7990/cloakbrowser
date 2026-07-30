"""Authenticated Shop-check smoke test (plan Task 16).

Drives the REAL manager pipeline end to end — 711 proxy provisioning, profile
creation, headed browser launch, per-email Shop check, export, and cleanup —
against a SMALL set of OWNED test accounts. Nothing is mocked in real mode.

Run it on the Windows box that has the cloakbrowser binary and network access.

Config via environment (never hardcode secrets or accounts):

    SMOKE_711_USER, SMOKE_711_PASS   711 account (builds the sticky routes)
    SMOKE_EMAILS                     comma-separated OWNED test emails (start with 1-2)
    SMOKE_REGION                     optional two-letter proxy region (e.g. US)
    SMOKE_PER_PROFILE                optional emails-per-profile (1-5, default 5)
    SMOKE_MAX_PARALLEL               optional parallel profiles (1-5, default 2)
    SMOKE_DATA_ROOT                  optional; default: a fresh temp dir

Usage (PowerShell):

    $env:SMOKE_711_USER="..."; $env:SMOKE_711_PASS="..."
    $env:SMOKE_EMAILS="me@owned-account.com"
    python scripts/shop_check_smoke.py

Self-test (no browser, no network, no creds — proves THIS harness is correct):

    python scripts/shop_check_smoke.py --selftest

Output: a PASS/FAIL line per check and a sanitized evidence file. No email, no
proxy secret, and no full address is ever printed or written.
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# Repo root on path so `manager_backend` and `cloakbrowser` import when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manager_backend.config import ManagerSettings  # noqa: E402
from manager_backend.features.proxies.credentials import ProxyCredential  # noqa: E402
from manager_backend.features.shop_check import service  # noqa: E402
from manager_backend.features.shop_check.cleanup import cleanup_run, resolve_owned_profile_ids  # noqa: E402
from manager_backend.features.shop_check.export import export_run  # noqa: E402
from manager_backend.features.shop_check.schemas import ShopCheckRunCreate  # noqa: E402
from manager_backend.main import create_app  # noqa: E402
from manager_backend.models import Profile, ShopCheckEmail  # noqa: E402

_TERMINAL = {"completed", "completed_with_issues", "cancelled", "failed"}


class Report:
    """Collects PASS/FAIL checks and sanitized evidence; nothing sensitive."""

    def __init__(self) -> None:
        self.checks: list[tuple[str, bool, str]] = []
        self.evidence: dict[str, object] = {}

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append((name, bool(ok), detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        return ok

    def note(self, key: str, value: object) -> None:
        self.evidence[key] = value

    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.checks)


def _install_selftest_fakes(app, emails):
    """Inject fakes so the harness runs with no browser/network/creds — used to
    verify the harness itself, mirroring test_shop_check_production_assembly."""
    from manager_backend.features.proxies.credentials import MemoryCredentialStore
    from manager_backend.features.proxies.providers import GeneratedProxy
    from manager_backend.features.proxies.testing import QuickTestResult

    class _Provider:
        def generate(self, provider, credential, count, country, session_type):
            # Distinct session directive per generated route (unique-session check).
            return [
                GeneratedProxy("global.711proxy.com", 20000, f"u-sess-{id(object())}", "SECRET")
                for _ in range(count)
            ]

    class _Tester:
        def run_fast(self, url, timeout_seconds=5):
            return QuickTestResult("203.0.113.5", True, 100, datetime(2026, 7, 30, tzinfo=timezone.utc))

    class _Launcher:
        def start_and_wait_ready(self, profile_id, *, timeout_seconds, is_cancelled):
            return f"cdp://{profile_id}"

        def stop(self, profile_id):
            pass

    class _Cdp:
        _cycle = ["phone_otp_required", "login_success", "account_not_found"]
        _n = {"i": 0}

        def __init__(self, cdp_endpoint):
            pass

        def goto(self, url):
            pass

        def fill_email(self, email):
            pass

        def submit(self):
            pass

        def page_html(self):
            # Rotate deterministic outcomes; phone page carries a parseable hint.
            which = _Cdp._cycle[_Cdp._n["i"] % len(_Cdp._cycle)]
            _Cdp._n["i"] += 1
            self._which = which
            return {
                "phone_otp_required": "<p>We texted a code to the phone number ending in 34.</p>",
                "login_success": "<a href='/logout'>Log out</a><p>You're signed in.</p>",
                "account_not_found": "<p>We couldn't find an account with that email address.</p>",
            }[which]

        def phone_hint(self):
            return "+84 ••• ••34"

        def clear_origin_state(self):
            pass

        def screenshot(self):
            return None

        def close(self):
            pass

    store = MemoryCredentialStore()
    app.state.credential_store = store
    coord = app.state.shop_check_coordinator
    coord._store = store
    coord._provider_client = _Provider()
    coord._tester = _Tester()
    coord._launcher = _Launcher()
    import manager_backend.features.shop_check.browser as browser_mod
    browser_mod.CdpShopSession = _Cdp
    return store


def main() -> int:
    selftest = "--selftest" in sys.argv
    per_profile = int(os.environ.get("SMOKE_PER_PROFILE", "5"))
    max_parallel = int(os.environ.get("SMOKE_MAX_PARALLEL", "2"))
    region = os.environ.get("SMOKE_REGION") or None
    data_root = Path(os.environ.get("SMOKE_DATA_ROOT") or tempfile.mkdtemp(prefix="shopchk-smoke-"))

    if selftest:
        emails = ["a@example.com", "b@example.com", "c@example.com"]
        user_711 = pass_711 = "selftest"
    else:
        user_711 = os.environ.get("SMOKE_711_USER", "")
        pass_711 = os.environ.get("SMOKE_711_PASS", "")
        emails = [e.strip() for e in os.environ.get("SMOKE_EMAILS", "").split(",") if e.strip()]
        if not (user_711 and pass_711 and emails):
            print("Set SMOKE_711_USER, SMOKE_711_PASS, and SMOKE_EMAILS (see module docstring).")
            return 2

    settings = ManagerSettings(
        data_root=data_root,
        allowed_origin="http://127.0.0.1:5173",
        install_token="smoke-token",
        auto_backup_enabled=False,
    )
    app = create_app(settings)
    report = Report()
    report.note("mode", "selftest" if selftest else "authenticated")
    report.note("email_count", len(emails))
    report.note("per_profile", per_profile)

    store = _install_selftest_fakes(app, emails) if selftest else app.state.credential_store
    # Provide the 711 account credentials the provisioner will use.
    store.put("proxy-provider:seveneleven", ProxyCredential(user_711, pass_711))

    coordinator = app.state.shop_check_coordinator
    session_factory = app.state.session_factory
    try:
        # --- create + run ---------------------------------------------------
        with session_factory() as session:
            payload = ShopCheckRunCreate(
                email_text="\n".join(emails),
                emails_per_profile=per_profile,
                max_parallel=max_parallel,
                region=region,
                authorized_only_ack=True,
            )
            created = service.create_run(session, store, payload, session_factory)
            run_id = created["run"]["id"]
        valid = created["input_summary"]["valid"]

        t0 = time.monotonic()
        with session_factory() as session:
            coordinator.start(session, run_id)
        timeout = float(os.environ.get("SMOKE_TIMEOUT", "600"))
        detail = None
        while time.monotonic() - t0 < timeout:
            with session_factory() as session:
                detail = service.get_run_detail(session, run_id)
            if detail["status"] in _TERMINAL:
                break
            time.sleep(0.25)
        elapsed = round(time.monotonic() - t0, 1)
        report.note("run_seconds", elapsed)
        report.note("final_status", detail["status"])
        report.note("result_counts", detail["result_counts"])

        report.check("run reached a terminal status", detail["status"] in _TERMINAL,
                     f"{detail['status']} in {elapsed}s")

        # --- grouping -------------------------------------------------------
        expected_workers = math.ceil(valid / per_profile)
        report.check("five-email grouping", detail["worker_count"] == expected_workers,
                     f"{detail['worker_count']} workers for {valid} emails @ {per_profile}/profile")

        with session_factory() as session:
            emails_rows = session.query(ShopCheckEmail).filter_by(run_id=run_id).all()
            workers = detail["workers"]
            profile_ids = [w["profile_id"] for w in workers if w["profile_id"]]
            proxy_ids = [w["proxy_id"] for w in workers if w["proxy_id"]]
            seeds = [
                session.get(Profile, pid).fingerprint_seed
                for pid in profile_ids
                if session.get(Profile, pid) is not None
            ]

        # --- provisioning + uniqueness -------------------------------------
        report.check("every worker owns a proxy (preflight ran)",
                     len(proxy_ids) == detail["worker_count"] and all(proxy_ids))
        report.check("unique session directive per profile (distinct proxies)",
                     len(set(proxy_ids)) == len(proxy_ids))
        report.check("unique fingerprint seed per profile",
                     len(set(seeds)) == len(seeds) and len(seeds) == len(profile_ids))

        # --- per-email results (state reset implied by independent outcomes) -
        terminal = [e for e in emails_rows if e.state == "terminal" and e.result]
        report.check("every assigned email got a terminal result",
                     len(terminal) == len(emails_rows) and len(emails_rows) == valid,
                     f"{len(terminal)}/{len(emails_rows)} terminal")

        # --- export ---------------------------------------------------------
        with session_factory() as session:
            export = export_run(session, store, settings, run_id)
        csv_exists = Path(export["results_csv"]).is_file()
        txt_exists = Path(export["matched_txt"]).is_file()
        report.check("export wrote results.csv + matched.txt", csv_exists and txt_exists)
        report.note("export_dir", export["output_dir"])
        report.note("matched_count", export["matched_count"])
        # No full email in the CSV (masked-only).
        csv_text = Path(export["results_csv"]).read_text(encoding="utf-8") if csv_exists else ""
        report.check("no full email address in results.csv",
                     all(e not in csv_text for e in emails))

        # --- cleanup (only run-owned profiles) ------------------------------
        # A control profile must survive cleanup.
        with session_factory() as session:
            control = Profile(name="smoke-control", fingerprint_seed="control-seed-xyz",
                              fingerprint_config_hash="0" * 64)
            session.add(control)
            session.commit()
            control_id = control.id
            owned = resolve_owned_profile_ids(session, run_id)
        with session_factory() as session:
            cleanup = cleanup_run(
                session, settings, app.state.runtime_manager, run_id,
                expected_profile_count=len(owned), session_factory=session_factory,
            )
        report.check("cleanup deleted the owned profiles",
                     cleanup["deleted"] == len(owned) and cleanup["failed"] == 0,
                     f"deleted {cleanup['deleted']}/{len(owned)}")
        with session_factory() as session:
            control_survived = session.get(Profile, control_id) is not None
            owned_gone = all(session.get(Profile, pid) is None for pid in owned)
        report.check("cleanup left the control profile untouched", control_survived)
        report.check("owned profile rows removed", owned_gone)

    finally:
        coordinator.shutdown()

    # --- sanitized evidence file -------------------------------------------
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence_path = data_root / f"shop_check_smoke_{stamp}.txt"
    lines = [f"Shop-check smoke — {stamp}", ""]
    lines += [f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else "")
              for name, ok, detail in report.checks]
    lines += ["", "Evidence (sanitized):"]
    lines += [f"  {k} = {v}" for k, v in report.evidence.items()]
    evidence_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print()
    print(f"Evidence: {evidence_path}")
    print("RESULT:", "PASS" if report.ok() else "FAIL")
    return 0 if report.ok() else 1


if __name__ == "__main__":
    raise SystemExit(main())
