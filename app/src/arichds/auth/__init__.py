"""Authentication — user JWT only (M2-1).

SPEC §3.2 and CLAUDE.md: the only way in is a user's Access Token. There is no
API key, no inbound M2M surface, and no roles/permissions tables — a two-value
:class:`arichds.auth.roles.Role` enum column carries the whole authorization
model.

The modules here are HTTP-free on purpose: :mod:`arichds.auth.security` knows
about hashes and JWTs, :mod:`arichds.auth.service` knows about a ``Session``,
and only :mod:`arichds.api.auth` / :mod:`arichds.api.deps` know about status
codes.
"""

from __future__ import annotations
