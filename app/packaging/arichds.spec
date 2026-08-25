# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for arichds.exe.

One-folder (`--onedir`) build of the single-process Windows delivery: FastAPI
API + Poller + the bundled React SPA (SPEC §4). One-folder rather than one-file
for faster iteration and quicker startup — no per-launch unpack — and the whole
`dist/arichds/` folder ships as a unit that Inno Setup drops into
`Program Files\\ARICHDS`.

Build from `app/`:  pyinstaller packaging/arichds.spec
(or run packaging/build.ps1, which builds the SPA first).
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# SPECPATH is injected by PyInstaller = the directory holding this .spec.
APP_ROOT = Path(SPECPATH).parent  # noqa: F821  (SPECPATH is a PyInstaller global)
REPO = APP_ROOT.parent
SRC = APP_ROOT / "src"
FE_DIST = REPO / "web" / "dist"

# collect_submodules() imports the package to walk it and runs at spec-eval time
# — BEFORE Analysis applies `pathex`. Put src/ on sys.path now, or
# collect_submodules("arichds") silently returns nothing and the exe fails at
# runtime with "No module named 'arichds'".
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if not (FE_DIST / "index.html").is_file():
    raise SystemExit(
        f"Web UI not built at {FE_DIST}. Build it first: `pnpm build` in web/ "
        f"(packaging/build.ps1 does this for you)."
    )

# ── Data files bundled into the frozen root ──────────────────────────────────
datas = [
    # `fe_static.resolve_fe_dist()` looks for <_MEIPASS>/fe_dist when frozen.
    (str(FE_DIST), "fe_dist"),
    # `db.migrate.migrations_dir()` looks for <_MEIPASS>/arichds/migrations.
    # Alembic reads env.py, script.py.mako and versions/*.py as FILES at
    # runtime, so they must ship as data — bytecode in the archive is not enough.
    (str(SRC / "arichds" / "migrations"), "arichds/migrations"),
    # The vendor public key sits next to its module and is read at runtime.
    # Without it the exe refuses every Activation Code — and a limited-mode-only
    # smoke test would never notice.
    (str(SRC / "arichds" / "licensing" / "public_key.pem"), "arichds/licensing"),
]

# gurux ships OBISCodes.txt as package data; without it the association view
# breaks (a lesson from the v1 build).
datas += collect_data_files("gurux_dlms")

# ── Hidden imports ───────────────────────────────────────────────────────────
# The vendored GX*.py modules star-import gurux_*, which defeats static
# analysis, and Alembic's env.py is loaded by path at runtime — so both the
# app package and the gurux stack must be collected explicitly.
hiddenimports = []
hiddenimports += collect_submodules("arichds")
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("pydantic")
hiddenimports += collect_submodules("gurux_dlms")
hiddenimports += [
    "gurux_net",
    "gurux_serial",
    "gurux_common",
    "alembic",
    "sqlalchemy.dialects.sqlite",
    # Same reason `sqlalchemy.dialects.sqlite` is listed one line up:
    # SQLAlchemy resolves a dialect through an entry point at `create_engine`
    # time, which PyInstaller's static analysis cannot see. The Database
    # Destination (issue #46) builds a `mysql+pymysql://` URL at runtime from
    # `settings` rows, so neither name appears in any import statement — a
    # missing hidden import here produces an exe that works in dev and fails
    # only on the customer machine, at the first sync cycle.
    "sqlalchemy.dialects.mysql",
    "pymysql",
    # The vendored Gurux wrappers are imported by bare name from
    # arichds/vendor/gurux/__init__.py, which puts its own directory on sys.path.
    "GXDLMSReader",
    "GXSettings",
    "GXCmdParameter",
    "GXDLMSSecureClient2",
]

a = Analysis(
    [str(APP_ROOT / "run_arichds.py")],
    pathex=[str(SRC), str(SRC / "arichds" / "vendor" / "gurux")],
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
    name="arichds",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="arichds",
)
