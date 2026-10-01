# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for probe_lp_buffer.exe — a carry-to-site diagnostic.

**One-file**, the same shape `probe_tcc.spec` and `probe_lp_compare.spec` use and
for the same reason: this exe is copied onto a customer machine that has no
Python, no venv and often no internet, so one file to copy is the whole point.

It answers one question at the site: *why does this meter refuse its load
profile?* — see `scripts/probe_lp_buffer.py` for what it asks and what each
answer rules out. It bundles no SPA, no migrations and no licensing key: the
probe reads a meter and prints, and it never writes to the meter or opens the
database.

Build from `app/`:  pyinstaller packaging/probe_lp_buffer.spec
Result:             app/dist/probe_lp_buffer.exe
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
    [str(APP_ROOT / "scripts" / "probe_lp_buffer.py")],
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
    name="probe_lp_buffer",
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
