"""Vendored Gurux DLMS wrappers — copied verbatim from v1, never edited.

``GXDLMSReader.py``, ``GXSettings.py``, ``GXDLMSSecureClient2.py`` and
``GXCmdParameter.py`` are byte-identical copies of the files that sit at the
v1 worker root. They are adapted from the Gurux DLMS sample code and use
camelCase throughout; renaming anything in them would break API compatibility
with the ``gurux_dlms`` package they drive (SPEC §4: "Gurux DLMS (vendored
``GX*.py`` ห้ามแก้ API").

They import **each other by bare module name** (``from GXCmdParameter import
GXCmdParameter``), which only resolves when their own directory is on
``sys.path``. Rather than edit the vendored files, this package puts its own
directory on ``sys.path`` and re-exports the two classes the drivers need. All
ARICHDS code imports from here::

    from arichds.vendor.gurux import GXDLMSReader, GXSettings

``ruff`` excludes this directory (see ``pyproject.toml``); the per-file lint
exemptions from ``cewe-worker/ruff.toml`` are carried over as well.
"""

from __future__ import annotations

import sys
from pathlib import Path

_VENDOR_DIR = str(Path(__file__).resolve().parent)
if _VENDOR_DIR not in sys.path:
    sys.path.insert(0, _VENDOR_DIR)

from GXDLMSReader import GXDLMSReader
from GXSettings import GXSettings

__all__ = ["GXDLMSReader", "GXSettings"]
