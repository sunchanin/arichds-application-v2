# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for probe_tcc.exe — a carry-to-site diagnostic.

**One-file**, unlike `arichds.spec`'s one-folder product build, and deliberately
so: this exe exists to be copied onto a customer machine that has no Python, no
venv and often no internet. One file to copy is the whole point; the per-launch
unpack cost that rules one-file out for a long-running service is irrelevant to
a diagnostic that runs for a few seconds. v1 packaged its own field probe the
same way (`cewe-worker/build-probe/test_mitsu_serial.spec`).

It bundles no SPA, no Alembic migrations and no licensing public key — the probe
reads a meter and prints; it never opens the database, serves a page, or checks
a license.

Build from `app/`:  pyinstaller packaging/probe_tcc.spec
Result:             app/dist/probe_tcc.exe
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# SPECPATH is injected by PyInstaller = the directory holding this .spec.
APP_ROOT = Path(SPECPATH).parent  # noqa: F821  (SPECPATH is a PyInstaller global)
SRC = APP_ROOT / "src"

# collect_submodules() imports the package to walk it and runs at spec-eval time
# — BEFORE Analysis applies `pathex`. Put src/ on sys.path now, or the collect
# below silently returns nothing and the exe fails at runtime with
# "No module named 'arichds'" (the same trap arichds.spec documents).
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# gurux ships OBISCodes.txt as package data; without it the association view
# breaks (a lesson from the v1 build).
datas = collect_data_files("gurux_dlms")

# The vendored GX*.py modules star-import gurux_*, which defeats static
# analysis, so the gurux stack is collected explicitly. Only the acquisition
# subtree is collected from `arichds` — the probe touches no other package, and
# whatever acquisition imports is followed statically anyway.
hiddenimports = []
hiddenimports += collect_submodules("arichds.acquisition")
hiddenimports += collect_submodules("gurux_dlms")
hiddenimports += [
    "gurux_net",
    "gurux_serial",
    "gurux_common",
    # The vendored Gurux wrappers are imported by bare name from
    # arichds/vendor/gurux/__init__.py, which puts its own directory on sys.path.
    "GXDLMSReader",
    "GXSettings",
    "GXCmdParameter",
    "GXDLMSSecureClient2",
]

a = Analysis(
    [str(APP_ROOT / "scripts" / "probe_tcc.py")],
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
    a.binaries,
    a.datas,
    [],
    name="probe_tcc",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
