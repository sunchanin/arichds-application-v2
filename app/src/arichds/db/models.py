"""SQLAlchemy 2 models — M1 and M2-1 tables.

The full v2 schema is 13 tables (SPEC §4); M1 landed the two the walking
skeleton needs and M2-1 adds the two auth needs. The rest arrive module by
module, each via its own Alembic migration — never by widening this file
speculatively.

``interval_readings`` is deliberately a *subset* of the COSEM shape defined in
REMAKE-PLAN §6.1. Its normalization contract is absolute and applies from row
one: **always UTC, always kWh, column names match the unit actually stored**.
The conversion happens in the driver at write time, never at read time.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from arichds.auth.roles import Role


class Base(DeclarativeBase):
    """Declarative base for every ARICHDS table."""


class Device(Base):
    """A meter configured on this machine.

    ``transport`` is a JSON column holding the Transport Endpoint description —
    ``{"kind": "net", "host": ..., "port": ...}`` for TCP. Keeping it as JSON is
    the v2 consolidation decision (SPEC §4: devices absorbs device_settings /
    device_status / device_capture_objects as JSON columns) and means adding
    serial fields in M3 needs no migration of this column.

    ``site_code``, ``customer`` and ``meter_number`` are **record-only** fields:
    v1 validated them and stored them and nothing else ever read them
    (SPEC §3.3 — "ห้ามประดิษฐ์พฤติกรรมให้"). Do not attach behaviour to them.

    Attributes:
        id: Surrogate primary key.
        name: Operator-facing label, unique per machine.
        brand: Meter brand, e.g. ``"cewe"``. Data the operator/catalog supplies,
            never a branch — nothing derives behaviour from it.
        model: Meter model, e.g. ``"prometer100"``. Resolves the driver via the
            driver registry.
        meter_serial: The Meter Serial read **off the meter** (ADR 0005), unique
            across the devices that currently exist. Nullable only because rows
            created before M3 were never probed; code must never assume it is
            set. Deleting a device frees its serial for reuse.
        site_name: Which site this meter is at — required by the form, and how
            the Devices tree groups. Pre-M3 rows carry the placeholder the
            migration wrote.
        site_code: Record-only.
        customer: Record-only.
        meter_number: Record-only — an operator-entered label, NOT the Meter
            Serial (CONTEXT.md).
        group_name: Free-text group; a distinct query feeds the form's dropdown.
        transport: Transport Endpoint description (JSON).
        password: DLMS authentication password. Never logged, never returned by
            the API.
        block_cipher_key: DLMS global unicast encryption key. Unused in M3, used
            by the HLS models in M4. Never logged, never returned by the API.
        authentication_key: DLMS authentication key. Same handling.
        first_bill_date: When billing periods start. The column lives here; the
            period logic is M6.
        bill_day_feb28/bill_day_feb29/bill_day_30/bill_day_31: Which day of the
            month closes a period, per month length. Columns only until M6.
        enabled: Whether the Poller should read this device (CONTEXT.md — Pause).
        created_at: Row creation time (UTC).
    """

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    brand: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    # Unique AND nullable on purpose: SQLite permits many NULLs in a unique
    # index, which is exactly the "not yet identified" state pre-M3 rows are in.
    meter_serial: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, default=None)
    # The server_default is duplicated verbatim in migration 0003 rather than
    # shared through a constant: a migration must freeze the world as it was
    # when it was written, so it may not import anything that can be edited
    # later. Both sides say "Unknown site"; changing one without the other is a
    # bug the migration tests catch.
    site_name: Mapped[str] = mapped_column(String(255), server_default="Unknown site")
    site_code: Mapped[str | None] = mapped_column(String(80), default=None)
    customer: Mapped[str | None] = mapped_column(String(255), default=None)
    meter_number: Mapped[str | None] = mapped_column(String(80), default=None)
    group_name: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
    transport: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    password: Mapped[str] = mapped_column(String(128), default="")
    block_cipher_key: Mapped[str | None] = mapped_column(String(255), default=None)
    authentication_key: Mapped[str | None] = mapped_column(String(255), default=None)
    first_bill_date: Mapped[date | None] = mapped_column(Date, default=None)
    bill_day_feb28: Mapped[int | None] = mapped_column(default=None)
    bill_day_feb29: Mapped[int | None] = mapped_column(default=None)
    bill_day_30: Mapped[int | None] = mapped_column(default=None)
    bill_day_31: Mapped[int | None] = mapped_column(default=None)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    readings: Mapped[list[IntervalReading]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def transport_endpoint(self) -> str:
        """The Poller's lock key — ``host:port`` for TCP (CONTEXT.md).

        Locks key on the endpoint, not the device: devices sharing a line queue
        behind one lock. For M1 only ``net`` exists; serial arrives in M3/M4 and
        will return the COM port name here.
        """
        transport = self.transport or {}
        if transport.get("kind") == "serial":
            return str(transport.get("serial_port", ""))
        return f"{transport.get('host', '')}:{transport.get('port', '')}"


class IntervalReading(Base):
    """One row of time-series meter data in COSEM shape.

    Always UTC, always kWh, regardless of whether the Source was DLMS or Modbus
    (CONTEXT.md — Interval Reading). M1 stores the instantaneous subset: V/I per
    phase, frequency, and the total import energy register.

    Attributes:
        id: Surrogate primary key.
        device_id: Owning device.
        read_at: When the meter reported the value — **UTC, timezone-aware**.
        source: Which acquisition path produced it (``dlms`` / ``modbus``). A
            property of the reading, never a branch in read-path code.
        interval: Cadence label, e.g. ``"60s"`` for the M1 monitor poll and
            ``"15m"`` for load profile later.
        volt_l1/volt_l2/volt_l3: Phase-to-neutral voltage (V).
        current_l1/current_l2/current_l3: Line current (A).
        freq: Frequency (Hz).
        import_active_kwh: Cumulative active energy import — **kWh**, already
            divided down from the meter's raw Wh by the driver.
        created_at: When this row was written (UTC).
    """

    __tablename__ = "interval_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(16))
    interval: Mapped[str] = mapped_column(String(16))

    volt_l1: Mapped[float | None] = mapped_column(default=None)
    volt_l2: Mapped[float | None] = mapped_column(default=None)
    volt_l3: Mapped[float | None] = mapped_column(default=None)
    current_l1: Mapped[float | None] = mapped_column(default=None)
    current_l2: Mapped[float | None] = mapped_column(default=None)
    current_l3: Mapped[float | None] = mapped_column(default=None)
    freq: Mapped[float | None] = mapped_column(default=None)
    import_active_kwh: Mapped[float | None] = mapped_column(default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    device: Mapped[Device] = relationship(back_populates="readings")

    __table_args__ = (
        # The monitor page's only query: latest row per device.
        Index("ix_interval_readings_device_read_at", "device_id", "read_at"),
    )


class User(Base):
    """An operator account on this machine (M2-1).

    Two levels only, carried in :attr:`role` — SPEC §3.2 collapses v1's
    roles/permissions tables into this one column. There is deliberately no
    ``api_token`` column (CLAUDE.md: no inbound M2M surface) and no
    ``is_active`` column: M2-2 locks an account out by *deleting* it, which
    cascades its tokens away in the same statement.

    Attributes:
        id: Surrogate primary key.
        username: Login name, unique per machine.
        password_hash: bcrypt hash. Never logged, never returned by the API.
        role: ``admin`` or ``user``.
        created_at: Row creation time (UTC).
        tokens: Every Access Token ever issued to this user.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    # VARCHAR with Python-side coercion rather than a native enum: SQLite would
    # otherwise get an unnamed CHECK constraint, which batch migrations
    # (render_as_batch=True) cannot reference when the table is later rebuilt.
    #
    # `values_callable` is load-bearing: without it SQLAlchemy persists the enum
    # member *names* (`ADMIN`/`USER`), which would put the column at odds with
    # every other place a Role is named — the API payload, the JWT `role` claim,
    # SPEC §3.2 and CONTEXT.md's Role entry all say `admin`/`user`.
    role: Mapped[Role] = mapped_column(
        SAEnum(
            Role,
            native_enum=False,
            length=16,
            create_constraint=False,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        )
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tokens: Mapped[list[UserToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class UserToken(Base):
    """One issued Access Token, stored **only** as a hash (M2-1).

    SPEC §3.2 / v1 INV-AUTH-04: the raw JWT never touches the database, so a
    stolen copy of ``arichds.db`` cannot be replayed as a session. Verification
    hashes the presented token and looks the digest up here.

    No ``ip_address`` / ``user_agent`` columns: the login log line carries the
    client IP, which is what the App Log (M7) actually shows, and the 13-table
    target stays lean.

    Attributes:
        id: Surrogate primary key.
        user_id: Owning user.
        token_hash: SHA-256 hex digest of the raw token.
        expires_at: When the token stops being accepted (UTC).
        revoked_at: When logout revoked it (UTC), or None while live.
        created_at: When it was issued (UTC).
    """

    __tablename__ = "user_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="tokens")
