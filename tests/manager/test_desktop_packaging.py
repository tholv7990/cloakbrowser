from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPOSITORY_ROOT / "src-tauri" / "plasma-backend.spec"
MIGRATIONS_DIRECTORY = REPOSITORY_ROOT / "manager_backend" / "migrations"


def _packaging_configuration() -> dict[str, object]:
    spec_prefix, separator, _ = SPEC_PATH.read_text(encoding="utf-8").partition(
        "\na = Analysis("
    )
    assert separator, "spec must define its data files before Analysis"

    configuration = {"SPEC": str(SPEC_PATH)}
    exec(compile(spec_prefix, str(SPEC_PATH), "exec"), configuration)
    return configuration


def test_sidecar_packages_migrations_from_repository_root() -> None:
    configuration = _packaging_configuration()
    migration_source, destination = next(
        data_file
        for data_file in configuration["datas"]
        if data_file[1] == "manager_backend/migrations"
    )

    assert destination == "manager_backend/migrations"
    assert Path(migration_source) == MIGRATIONS_DIRECTORY
    assert MIGRATIONS_DIRECTORY.is_dir()
    assert (
        MIGRATIONS_DIRECTORY / "versions" / "0020_fingerprint_overrides.py"
    ).is_file()
