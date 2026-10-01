"""Central Push — the Data-out Destination that sends Billing, Load Profile,
the Energy Summary and the meter roster to the team's own server (ADR 0024,
CONTEXT.md — Central Push).

**A new module, separate from `arichds.dataout`** (REMAKE-PLAN, "Central
Push (ADR 0024)"): the Database Destination and the Central Push are two
transports with two contracts (SPEC §3.10), and they share no code —
only the pattern (settings rows, a status record held in memory, last in
the scheduler queue).

Ticket 07 lands the configuration, the published contract and the admin
endpoints. The cycle that actually talks to a server — asking what it
holds, sending rows, updating :mod:`.status` — is ticket 08.
"""

from __future__ import annotations
