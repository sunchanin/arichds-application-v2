"""Billing capture (M6b, issue #22) — PDF/xlsx documents for closed Billing
Readings, written to an operator-chosen folder (ADR 0010).

Path derivation (:mod:`arichds.capture.paths`), rendering
(:mod:`arichds.capture.pdf` / :mod:`arichds.capture.xlsx`, off the shared
section definitions in :mod:`arichds.capture._render_shared`), and the
hardened write (:mod:`arichds.capture.write`) each live in their own module;
:mod:`arichds.capture.service` is what wires them together for both callers —
the eager write in :mod:`arichds.acquisition.billing` and the render-on-miss
download in :mod:`arichds.api.billing`.
"""

from __future__ import annotations
