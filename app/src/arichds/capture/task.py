"""The ``installer/``<->``app/`` contract for the LOCAL SERVICE scheduled
task that launches the headless capture browser (issue #40, replacing #38's
Part A).

Only the ``msedge.exe`` launch has to leave the SYSTEM account — the service
itself stays ``LocalSystem`` so an operator-chosen ``capture_dir`` under
``C:\\Users\\...`` stays writable (ADR 0017's Correction). The browser is
started through a Windows scheduled task registered to
``NT AUTHORITY\\LOCAL SERVICE`` at install time
(``installer/register-capture-task.ps1``), triggered by the service with
``schtasks /run`` (:mod:`arichds.capture.screenshot`).

**Nothing here is imported at runtime except the two names below** — this
module exists so :mod:`tests.test_capture_task_contract` has one place to pin
the installer script and the ``.iss`` against, the same shape
:mod:`arichds.capture.dom` uses for the ``web/``<->``app/`` contract. No DB,
no subprocess, no rendering.
"""

from __future__ import annotations

#: The scheduled task's name (decision D11, issue #40) — root of the task
#: library, no folder, since a folder buys nothing and leaves an empty one
#: behind on uninstall.
CAPTURE_TASK_NAME = "ARICHDS Capture Browser"

#: The fixed Edge flags the registered task's action carries — exactly
#: today's list in ``capture/screenshot.py``'s Edge launch, minus the
#: executable path (the task action supplies that) and minus
#: ``--user-data-dir=...`` (the installer parameterises that with
#: ``Settings.tmp_dir``, decision D2 — the task's arguments are fixed at
#: install time, so the profile directory is no longer per-capture).
#:
#: Two flag decisions worth recording explicitly here rather than leaving to
#: guesswork the next time someone diffs this list against a prototype:
#:
#: * ``--hide-scrollbars`` — present. The Billing table renders under
#:   ``scroll={{ x: tableWidth }}``, so an unhidden scrollbar could land in
#:   the image. That is chrome the browser adds, not part of the page
#:   ADR 0017 decision 3 approved truncating — hiding it is not the same
#:   decision as widening the viewport, which stays untouched.
#: * ``--no-sandbox`` — **deliberately absent.** It weakens Chromium's
#:   process sandbox and there is no evidence it is needed: the sandbox is a
#:   low-privilege-process concern, and ``NT AUTHORITY\\LOCAL SERVICE`` — the
#:   account the scheduled task now runs Edge under (issue #40) — is already
#:   a low-privilege account, unlike the root/administrative contexts that
#:   usually force this flag.
EDGE_TASK_ARGUMENTS: tuple[str, ...] = (
    "--headless=new",
    "--disable-gpu",
    "--hide-scrollbars",
    "--no-first-run",
    "--no-default-browser-check",
    "--remote-debugging-port=0",
    "about:blank",
)
