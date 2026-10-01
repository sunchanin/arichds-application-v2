"""The Load Profile CSV export — the Export Format settings and the
auto-export job that appends under them (M7 slice 3, issue #30).

Two modules:

* :mod:`arichds.export.format` — pure row/filename formatting, no I/O.
* :mod:`arichds.export.csv_export` — the exporter: watermark, skew cap,
  per-device lock, the hardened file write.

**Never imports the machine-wide kilo/base render setting** (ADR 0013, D-1).
The CSV is a contract an operator's downstream tooling appends to for
months; the header is written once, so its unit must never move. Nothing in
this package may import the capture package's shared rendering helpers,
reference that setting's storage key, or divide a value by anything — a
source-level guard in the test suite enforces this literally, so keep this
paragraph itself free of those two names too.
"""

from __future__ import annotations
