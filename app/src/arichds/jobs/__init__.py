"""Periodic jobs — one scheduler thread, one registry (M5a-2, issue #16).

The package holds the scheduler and the registry of what it runs. **Job
implementations live in their own modules**, next to the domain they belong to
(the load-profile cycle is in :mod:`arichds.acquisition.load_profile`, the
billing cycle is in :mod:`arichds.acquisition.billing` (M6a, issue #21), and
M5c's retention and backup jobs in :mod:`arichds.db.retention` and
:mod:`arichds.db.backup` — their domain is the rows and the file, not a meter);
only the registry entry lives here. That is what made adding billing's
auto-read one entry in a list plus a function — and what M8's sync will be too
— never a new thread and never a new scheduler class (REMAKE-PLAN §3, which
counts v1's seven `_DaemonScheduler` subclasses as over-engineering, one per
module rather than for any concurrency reason).
"""
