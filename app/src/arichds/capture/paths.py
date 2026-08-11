"""Path validation for the capture directory (ADR 0010; ported from v1
``cewe-worker/src/billing/paths.py``).

Two different uses, deliberately not conflated (decision 17, issue #22):

* :func:`validate_capture_dir_setting` — checked once, when an admin **saves**
  a new ``capture_dir`` value through ``PUT /api/billing/settings``. Checked
  against ``ARICHDS_CAPTURE_ALLOWLIST`` — if that is unset, there is **no**
  root restriction on ``capture_dir`` (v2's ``capture_dir`` is an operator
  setting, not env-configured, so defaulting the allowlist to it would be
  circular). The ``..``/absolute/drive-root/symlink checks apply
  unconditionally either way.
* :func:`ensure_within_allowlist` — the TOCTOU/defense-in-depth re-check run
  immediately before every write, on the fully-constructed
  ``<capture_dir>/<meter_serial>/<file>`` path. This **always** uses the
  resolved *current* ``capture_dir`` as its one root, regardless of whether
  ``ARICHDS_CAPTURE_ALLOWLIST`` is set — it is the check that stops a hostile
  ``meter_serial`` escaping, and it is never optional (decision 17).
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

#: Characters that are unsafe in a path component used as a directory name.
_SERIAL_UNSAFE_RE = re.compile(r"[/\\\x00]")


def validate_directory_setting(path_str: str, allowlist: list[Path], *, setting_name: str = "capture_dir") -> Path:
    """Validate a user-supplied directory setting.

    Generalised from the original ``capture_dir``-only body (D-13, M7 slice
    3, issue #30) so ``export_output_dir`` (F7 — v1 shared the same
    allowlist for its own ``output_dir``) can be validated by the identical
    rule, with the offending setting named correctly in the error sentence.
    :func:`validate_capture_dir_setting` is now a thin wrapper over this —
    zero behaviour change for capture_dir.

    Rejects: empty/whitespace, non-absolute, ``..`` components, a symlinked
    final path component (even one that resolves inside the allowlist — this
    closes the TOCTOU window a later retarget could open), a resolved
    filesystem/drive root, an existing path that is a file rather than a
    directory, and — only when *allowlist* is non-empty — a resolution
    outside every allowlisted root.

    Args:
        path_str: The raw value from the ``PUT`` body.
        allowlist: Resolved allowlist roots. Empty means "no root
            restriction" (decision 17).
        setting_name: The setting's name, used only in the error sentences —
            ``"capture_dir"`` or ``"export_output_dir"``.

    Returns:
        The resolved absolute path.

    Raises:
        ValueError: On any rejection, with an operator-actionable sentence.
    """
    if not path_str or not path_str.strip():
        raise ValueError(f"{setting_name} must not be empty")

    # Reject '..' before any resolution, to be explicit about the attack vector.
    if ".." in Path(path_str).parts:
        raise ValueError(f"{setting_name} must not contain '..' components")

    candidate = Path(path_str)
    if not candidate.is_absolute():
        raise ValueError(f"{setting_name} must be an absolute path, got {path_str!r}")

    try:
        final_stat = os.lstat(str(candidate))
    except OSError:
        final_stat = None  # Does not exist yet — nothing to check; it will be created on first write.
    if final_stat is not None:
        if stat.S_ISLNK(final_stat.st_mode):
            raise ValueError(f"{setting_name} must not be a symlink, got {path_str!r}")
        if not stat.S_ISDIR(final_stat.st_mode):
            # Otherwise this passes every check here and only fails later, as
            # an unhelpful 500, the moment a write tries to `mkdir` through it.
            raise ValueError(f"{setting_name} already exists and is not a directory: {path_str!r}")

    # resolve(strict=False) resolves symlinks for existing components without
    # raising on a non-existent tail — correct for a directory created later.
    resolved = candidate.resolve(strict=False)
    if resolved.parent == resolved:
        raise ValueError(f"{setting_name} must not be a filesystem or drive root, got {resolved!r}")

    if allowlist and not any(resolved == root or resolved.is_relative_to(root) for root in allowlist):
        raise ValueError(f"{setting_name} {path_str!r} is not within the permitted allowlist")

    return resolved


def validate_capture_dir_setting(path_str: str, allowlist: list[Path]) -> Path:
    """Validate a user-supplied ``capture_dir`` value.

    A thin wrapper over :func:`validate_directory_setting` with
    ``setting_name="capture_dir"`` — unchanged behaviour and unchanged error
    text from before D-13's generalisation.

    Args:
        path_str: The raw value from the ``PUT`` body.
        allowlist: Resolved allowlist roots from ``ARICHDS_CAPTURE_ALLOWLIST``.
            Empty means "no root restriction" (decision 17).

    Returns:
        The resolved absolute path.

    Raises:
        ValueError: On any rejection, with an operator-actionable sentence.
    """
    return validate_directory_setting(path_str, allowlist, setting_name="capture_dir")


def sanitize_meter_serial(serial: str) -> str:
    """Validate ``meter_serial`` for use as a directory path component.

    Rejects an empty string, ``/`` or ``\\``, a ``..`` substring, and a NUL
    byte — the same rules as v1 (``billing/paths.py:98-125``).

    Args:
        serial: Raw ``meter_serial`` from the ``BillingReading`` row.

    Returns:
        The serial string unchanged if valid.

    Raises:
        ValueError: On any rejection — the caller decides whether to skip the
            capture or 404/422 a download.
    """
    if not serial:
        raise ValueError("meter_serial must not be empty")
    if ".." in serial:
        raise ValueError(f"meter_serial contains '..': {serial!r}")
    if _SERIAL_UNSAFE_RE.search(serial):
        raise ValueError(f"meter_serial contains unsafe characters: {serial!r}")
    return serial


def ensure_within_allowlist(final_path: Path, allowlist: list[Path]) -> None:
    """Defence-in-depth re-check that *final_path* is within *allowlist*.

    Called immediately before every disk write as a TOCTOU guard against a
    ``capture_dir``/``meter_serial`` combination that bypasses entry
    validation through runtime path concatenation.

    Args:
        final_path: Fully-constructed target path (e.g.
            ``capture_dir/serial/file.pdf``).
        allowlist: The resolved ``capture_dir`` root — always one element in
            practice (decision 17), never the ``ARICHDS_CAPTURE_ALLOWLIST``
            roots used at setting-save time.

    Raises:
        ValueError: If *final_path* resolves outside every allowlist root.
    """
    resolved = final_path.resolve(strict=False)
    for root in allowlist:
        if resolved == root or resolved.is_relative_to(root):
            return
    raise ValueError(f"Final path {final_path!r} (resolved: {resolved!r}) is outside allowlist {allowlist!r}")
