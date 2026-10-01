"""Data-out — writing finished readings **outward** (CONTEXT.md, ADR 0016).

Today that is one Destination: the customer's own MariaDB/MySQL, the
**Database Destination** (SPEC §3.10, issue #46). The team's central-server
push (SPEC §3.8) is a different Destination with a different transport and a
different contract; ADR 0016 files both under one *concept*, deliberately not
under one *implementation*, so nothing here is written to be shared with it.

Deliberately **not** `export/`. That package is the Load Profile CSV — an
appended file which is a contract (ADR 0013) — and ADR 0021's Consequences
forbid the two sharing their local-time conversion helper, because they agree
today by coincidence of one constant rather than by contract.
"""
