"""The two authorization levels (M2-1).

SPEC §3.2 collapses v1's roles/permissions tables into one enum column: an
``admin`` manages meters, users, system settings and the license; a ``user``
sees every page, triggers manual reads and exports.

It lives in its own module — free of both the ORM and FastAPI — so the API layer
can compare roles without importing :mod:`arichds.db.models`.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """A user's authorization level.

    Attributes:
        ADMIN: Full control, including device create/delete and activation.
        USER: Read-only over the data pages.
    """

    ADMIN = "admin"
    USER = "user"
