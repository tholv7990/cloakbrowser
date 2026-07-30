"""Shop-check export: authoritative masked CSV + plaintext matched-email TXT.

Plaintext addresses land ONLY in matched.txt (the operator's deliverable); the
CSV stays masked. Writes are atomic and contained under the app export root.
"""

from __future__ import annotations

import csv
from pathlib import Path

from manager_backend.config import ManagerSettings
from manager_backend.features.proxies.credentials import MemoryCredentialStore, ProxyCredential
from manager_backend.features.shop_check import service
from manager_backend.features.shop_check.export import export_run, neutralize_cell
from manager_backend.features.shop_check.schemas import ShopCheckRunCreate
from manager_backend.models import ShopCheckEmail


def _settings(tmp_path) -> ManagerSettings:
    return ManagerSettings(
        data_root=tmp_path / "data",
        allowed_origin="http://127.0.0.1:5173",
        install_token="t",
        auto_backup_enabled=False,
    )


def _run_with_results(db_session_factory, store, results: dict[str, str]) -> str:
    """Create a run of the given {email: result}, then finalize each email."""
    text = "\n".join(results)
    with db_session_factory() as session:
        payload = ShopCheckRunCreate(
            email_text=text, emails_per_profile=5, max_parallel=1, authorized_only_ack=True
        )
        run_id = service.create_run(session, store, payload, db_session_factory)["run"]["id"]
        rows = session.query(ShopCheckEmail).filter_by(run_id=run_id).order_by(ShopCheckEmail.ordinal).all()
        # map masked back to the intended result via credential store username
        for row in rows:
            email = store.get(row.credential_ref).username
            service.finalize_email(session, row, results[email])
    return run_id


def test_neutralize_cell_blocks_formula_injection():
    for dangerous in ("=cmd()", "+1", "-2", "@x", "\tTAB", "\rCR"):
        assert neutralize_cell(dangerous).startswith("'")
    assert neutralize_cell("normal@example.com") == "normal@example.com"
    assert neutralize_cell("") == ""


def test_export_writes_masked_csv_and_plaintext_matched(db_session_factory, tmp_path):
    settings = _settings(tmp_path)
    store = MemoryCredentialStore()
    results = {
        "match1@example.com": "phone_otp_required",
        "match2@example.com": "phone_otp_required",
        "other@example.com": "account_not_found",
    }
    run_id = _run_with_results(db_session_factory, store, results)

    with db_session_factory() as session:
        result = export_run(session, store, settings, run_id)

    csv_path = Path(result["results_csv"])
    txt_path = Path(result["matched_txt"])
    assert csv_path.is_file() and txt_path.is_file()

    csv_text = csv_path.read_text(encoding="utf-8")
    # CSV is masked: no full address, but the result values are present.
    for email in results:
        assert email not in csv_text
    assert "phone_otp_required" in csv_text and "account_not_found" in csv_text

    matched = txt_path.read_text(encoding="utf-8").splitlines()
    # Plaintext deliverable: exactly the phone-OTP addresses, deduped, only there.
    assert sorted(matched) == ["match1@example.com", "match2@example.com"]
    assert "other@example.com" not in txt_path.read_text(encoding="utf-8")
    assert result["matched_count"] == 2
    assert result["total_rows"] == 3


def test_export_is_contained_under_export_root(db_session_factory, tmp_path):
    settings = _settings(tmp_path)
    store = MemoryCredentialStore()
    run_id = _run_with_results(db_session_factory, store, {"a@example.com": "login_success"})
    with db_session_factory() as session:
        result = export_run(session, store, settings, run_id)
    export_root = settings.export_root.resolve()
    assert Path(result["results_csv"]).resolve().is_relative_to(export_root)
    assert Path(result["matched_txt"]).resolve().is_relative_to(export_root)


def test_export_write_is_atomic_no_tmp_left(db_session_factory, tmp_path):
    settings = _settings(tmp_path)
    store = MemoryCredentialStore()
    run_id = _run_with_results(db_session_factory, store, {"a@example.com": "phone_otp_required"})
    with db_session_factory() as session:
        export_run(session, store, settings, run_id)
    leftovers = list(settings.export_root.rglob("*.tmp"))
    assert leftovers == []


def test_csv_rows_are_valid_and_never_contain_the_full_email(db_session_factory, tmp_path):
    settings = _settings(tmp_path)
    store = MemoryCredentialStore()
    sentinel = "sentinel.person@corp-example.com"
    run_id = _run_with_results(db_session_factory, store, {sentinel: "phone_otp_required"})
    with db_session_factory() as session:
        result = export_run(session, store, settings, run_id)

    with open(result["results_csv"], encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert sentinel not in str(rows[0])
    assert rows[0]["result"] == "phone_otp_required"
