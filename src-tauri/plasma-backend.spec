# PyInstaller spec — freezes the FastAPI backend into the Tauri sidecar.
#
# Build (Windows, from repo root, with the app installed in the venv):
#     pip install pyinstaller
#     pyinstaller src-tauri/plasma-backend.spec --noconfirm
# Output: dist/plasma-backend.exe  (ONEFILE). build.ps1 copies it to the Tauri
# sidecar slot, renamed to the host target triple:
#     src-tauri/binaries/plasma-backend-<triple>.exe
#
# onefile (not onedir): Tauri's `externalBin` bundles a single file, so a onedir
# exe+_internal folder wouldn't ship. The onefile unpack cost (~1-2s) is paid once
# at APP launch — NOT per profile — so it doesn't touch browser-start latency.
# console=False → no console window / taskbar entry. Authenticode-signing the
# installer + exe (see build.ps1) offsets onefile's AV-false-positive tendency.
# (Startup-perf follow-up: switch to onedir bundled via `resources` + a resource-path
#  spawn in main.rs, once someone can iterate a real Windows build.)

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


REPOSITORY_ROOT = Path(SPEC).resolve().parent.parent
MANAGER_BACKEND_ROOT = REPOSITORY_ROOT / "manager_backend"

hiddenimports = (
    collect_submodules("manager_backend")
    + collect_submodules("uvicorn")
    + [
        "cloakbrowser",
        "argon2",
        "argon2.low_level",
        "email_validator",
        "sqlalchemy.dialects.sqlite",
        "socks",
        "anyio",
        "httptools",
    ]
)

# The Alembic migrations + ini must ship so apply_schema()/upgrade head works.
datas = [
    (str(MANAGER_BACKEND_ROOT / "alembic.ini"), "manager_backend"),
    (str(MANAGER_BACKEND_ROOT / "migrations"), "manager_backend/migrations"),
]
datas += collect_data_files("cloakbrowser")

a = Analysis(
    [str(MANAGER_BACKEND_ROOT / "serve.py")],
    pathex=[str(REPOSITORY_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
# Onefile: bundle binaries + datas INTO the exe (no COLLECT) so `externalBin` ships
# a single self-contained file.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="plasma-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX increases AV false positives
    runtime_tmpdir=None,
    console=False,
)
