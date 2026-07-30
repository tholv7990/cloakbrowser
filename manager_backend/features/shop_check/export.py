"""Shop-check exports: an authoritative masked CSV and a plaintext matched TXT.

Two artifacts land under the app-controlled export root (`<data_root>/exports/
<run_id>/`), never a client-supplied path:

- `results.csv` — one row per email with the MASKED address plus the result and
  phone metadata. Every cell is neutralized against spreadsheet formula
  injection. No plaintext address appears here.
- `matched.txt` — the plaintext addresses that require phone OTP (the operator's
  deliverable), resolved from CredentialStore, deduped, one per line. This is the
  only place a full address is written to disk.

Writes are atomic (temp file + `os.replace`) so a crash never leaves a partial
file readable as authoritative. Raw addresses are never logged.
"""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path

from ...config import ManagerSettings
from ...errors import ManagerError
from ...features.proxies.credentials import CredentialStore
from ...models import ShopCheckEmail
from .schemas import RETRYABLE_RESULTS
from .service import require_run

# The result whose addresses form the matched-email deliverable.
_MATCHED_RESULT = "phone_otp_required"

_CSV_COLUMNS = [
    "ordinal", "email_masked", "result", "retryable",
    "phone_prefix", "phone_suffix", "phone_country_code",
    "phone_country_name", "phone_region_name", "phone_confidence", "checked_at",
]

# Leading characters a spreadsheet may interpret as a formula.
_FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")


def neutralize_cell(value: object) -> str:
    """Prefix a cell that a spreadsheet might execute as a formula with a quote."""
    text = "" if value is None else str(value)
    if text and text[0] in _FORMULA_LEADERS:
        return "'" + text
    return text


def _run_export_dir(settings: ManagerSettings, run_id: str) -> Path:
    root = settings.export_root.resolve()
    target = (root / run_id).resolve()
    if not target.is_relative_to(root):  # run_id can never escape the export root
        raise ManagerError("shop_check_export_path_invalid", "Invalid export path.", 400)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    os.replace(tmp, path)


def export_run(
    session, store: CredentialStore, settings: ManagerSettings, run_id: str
) -> dict:
    """Write results.csv + matched.txt for a run; return their paths and counts."""
    run = require_run(session, run_id)
    export_dir = _run_export_dir(settings, run_id)

    rows = (
        session.query(ShopCheckEmail)
        .filter_by(run_id=run_id)
        .order_by(ShopCheckEmail.ordinal)
        .all()
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_COLUMNS)
    for row in rows:
        writer.writerow(
            neutralize_cell(value)
            for value in (
                row.ordinal, row.email_masked, row.result,
                row.result in RETRYABLE_RESULTS,
                row.phone_prefix, row.phone_suffix, row.phone_country_code,
                row.phone_country_name, row.phone_region_name,
                row.phone_confidence,
                row.checked_at.isoformat() if row.checked_at else "",
            )
        )
    csv_path = export_dir / "results.csv"
    _atomic_write_text(csv_path, buffer.getvalue())

    # Plaintext deliverable: resolve full addresses for the matched result only,
    # dedupe while preserving order. Full addresses touch disk ONLY here.
    matched: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row.result != _MATCHED_RESULT:
            continue
        credential = store.get(row.credential_ref)
        if credential is None:
            continue
        address = credential.username
        if address not in seen:
            seen.add(address)
            matched.append(address)
    txt_path = export_dir / "matched.txt"
    _atomic_write_text(txt_path, "\n".join(matched) + ("\n" if matched else ""))

    run.output_dir = str(export_dir)
    session.commit()
    return {
        "run_id": run_id,
        "output_dir": str(export_dir),
        "results_csv": str(csv_path),
        "matched_txt": str(txt_path),
        "total_rows": len(rows),
        "matched_count": len(matched),
    }
