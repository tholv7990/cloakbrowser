# PyInstaller spec — freezes the FastAPI backend into the Tauri sidecar.
#
# Build (Windows, from repo root, with the app installed in the venv):
#     pip install pyinstaller
#     pyinstaller build/plasma-backend.spec --noconfirm
# Output: dist/plasma-backend/  (onedir). Copy the folder into the Tauri sidecar
# slot, renaming the exe to the target triple Tauri expects:
#     src-tauri/binaries/plasma-backend-x86_64-pc-windows-msvc.exe  (+ the _internal dir)
#
# onedir (not onefile): faster start + far fewer AV false positives. console=False
# so the sidecar has no console window / taskbar entry.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = (
    collect_submodules("manager_backend")
    + collect_submodules("uvicorn")
    + [
        "cloakbrowser",
        "argon2",
        "argon2.low_level",
        "email_validator",
        "sqlalchemy.dialects.sqlite",
        "anyio",
        "httptools",
    ]
)

# The Alembic migrations + ini must ship so apply_schema()/upgrade head works.
datas = [
    ("../manager_backend/alembic.ini", "manager_backend"),
    ("../manager_backend/migrations", "manager_backend/migrations"),
]
datas += collect_data_files("cloakbrowser")

a = Analysis(
    ["../manager_backend/serve.py"],
    pathex=[".."],
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
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="plasma-backend",
    debug=False,
    strip=False,
    upx=False,  # UPX increases AV false positives
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="plasma-backend",
)
