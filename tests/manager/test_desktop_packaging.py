from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPOSITORY_ROOT / "src-tauri" / "plasma-backend.spec"
NSIS_HOOKS_PATH = REPOSITORY_ROOT / "src-tauri" / "nsis-hooks.nsh"
MIGRATIONS_DIRECTORY = REPOSITORY_ROOT / "manager_backend" / "migrations"


def _packaging_configuration() -> dict[str, object]:
    spec_prefix, separator, _ = SPEC_PATH.read_text(encoding="utf-8").partition(
        "\na = Analysis("
    )
    assert separator, "spec must define its data files before Analysis"

    hooks = ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = lambda _package: []  # type: ignore[attr-defined]
    hooks.collect_submodules = lambda _package: []  # type: ignore[attr-defined]
    utils = ModuleType("PyInstaller.utils")
    utils.hooks = hooks  # type: ignore[attr-defined]
    pyinstaller = ModuleType("PyInstaller")
    pyinstaller.utils = utils  # type: ignore[attr-defined]

    configuration = {"SPEC": str(SPEC_PATH)}
    with patch.dict(
        sys.modules,
        {
            "PyInstaller": pyinstaller,
            "PyInstaller.utils": utils,
            "PyInstaller.utils.hooks": hooks,
        },
    ):
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


def test_preinstall_stops_shell_before_replacing_its_sidecar() -> None:
    hooks = NSIS_HOOKS_PATH.read_text(encoding="utf-8")
    macro_start = hooks.index("!macro NSIS_HOOK_PREINSTALL")
    macro_end = hooks.index("!macroend", macro_start)
    preinstall = hooks[macro_start:macro_end]

    stop_shell = (
        '!insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"'
    )
    stop_sidecar = "!insertmacro StopInstalledSidecar"

    assert preinstall.index(stop_shell) < preinstall.index(stop_sidecar)

    sidecar_macro_start = hooks.index("!macro StopInstalledSidecar")
    sidecar_macro_end = hooks.index("!macroend", sidecar_macro_start)
    sidecar_macro = hooks[sidecar_macro_start:sidecar_macro_end]
    assert "$INSTDIR\\plasma-backend.exe" in sidecar_macro
    assert "${RunningX64}" in sidecar_macro
    assert (
        "$WINDIR\\Sysnative\\WindowsPowerShell\\v1.0\\powershell.exe"
        in sidecar_macro
    )
    assert 'CheckIfAppIsRunning "plasma-backend.exe"' not in hooks
