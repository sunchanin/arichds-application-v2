"""The File Upload Destination — menu label **FTP** (SPEC §3.8, ADR 0025).

A third Data-out Destination (CONTEXT.md), distinct from the Database
Destination (:mod:`arichds.dataout`) and the Central Push
(:mod:`arichds.centralpush`): it copies the machine's **files** — the export
files and the Billing capture documents — to a server over one of three
protocols (SFTP, FTPS, HTTPS), one active at a time.

Imports nothing from :mod:`arichds.export` (the same ADR 0021 rule
:mod:`arichds.dataout` follows, for the same reason): the file on disk is the
contract, not a shared local-time helper.

Ticket 01 (this) lands the configuration — settings rows, the endpoints, the
in-memory status slot always reporting "no cycle has run" — and the nav entry.
Ticket 02 adds the cycle (:mod:`.cycle`, not yet written); tickets 03-05 add
the three transports.
"""

from __future__ import annotations
