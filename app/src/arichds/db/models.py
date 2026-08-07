"""SQLAlchemy 2 models — the M1, M2-1 and M3-2 tables.

The full v2 schema is 13 tables (SPEC §4); M1 landed the two the walking
skeleton needs, M2-1 adds the two auth needs and M3-2 adds ``device_events``.
The rest arrive module by module, each via its own Alembic migration — never by
widening this file speculatively.

``load_profile_readings`` is deliberately a *subset* of the COSEM shape defined
in REMAKE-PLAN §6.1. Its normalization contract is absolute and applies from row
one: **always UTC, always kWh, column names match the unit actually stored**.
The conversion happens in the driver at write time, never at read time. It was
empty from M3-4 until M5a-1: ADR 0007 stopped the Poller writing to it, and the
load-profile reader that fills it properly landed with issue #15 —
``acquisition/load_profile.py``, driven by Read now.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
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
        status: The last thing a read told us about this meter — one of
            ``online`` / ``offline`` / ``unknown``. ``paused`` is **not** storable:
            it is computed at read time from :attr:`enabled`
            (:class:`arichds.acquisition.status.DeviceStatus`).
        status_detail: A sentence explaining a non-online status, or None.
        status_checked_at: When a read last reported on this device (UTC), or
            None when nothing has (a resumed device, a model with no driver).
        consecutive_failures: How many failed reads in a row (ADR 0004's
            3-strikes rule).
        created_at: Row creation time (UTC).
        events: Every Device Event recorded for this device.
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
    # Three observable values — "online", "offline", "unknown" — named by
    # `arichds.acquisition.status.DeviceStatus`, which is deliberately NOT
    # imported here: that module imports this one, so the enum would close a
    # cycle. The literal default is duplicated verbatim in migration 0004 for
    # the same reason `site_name`'s "Unknown site" is (see above).
    status: Mapped[str] = mapped_column(String(16), default="unknown", server_default="unknown")
    status_detail: Mapped[str | None] = mapped_column(String(255), default=None)
    status_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # The strike counter behind ADR 0004's "offline after 3 consecutive failed
    # ticks". It lives in the database rather than in a worker's local variable
    # because `Poller.restart()` respawns every worker — adding one device would
    # otherwise reset the streak of every device on the site, and a genuinely
    # dead meter would never reach 3. A non-skipped tick already has to UPDATE
    # this row to refresh `status_checked_at`, so the counter rides that same
    # statement at no extra cost and can never disagree with the status it
    # produced. It also survives a Windows service restart.
    consecutive_failures: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    readings: Mapped[list[LoadProfileReading]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    events: Mapped[list[DeviceEvent]] = relationship(
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


class LoadProfileReading(Base):
    """One Interval Reading — time-series meter data in COSEM shape.

    Always UTC, always kWh, regardless of whether the Source was DLMS or Modbus
    (CONTEXT.md — Interval Reading; the glossary term names the row, this class
    and its table name what holds it).

    **Every row here is an interval the meter itself recorded.** The name
    changed with the contents at M3-4: ADR 0007 deleted the ``interval='60s'``
    rows the Poller used to write each tick, and what remains — 15-minute load
    profile (M5) and the Modbus cadences (M4b) — genuinely is load profile.
    Renaming was cheapest here, with the table empty and no reader, no push
    payload and no customer data attached to it yet.

    Attributes:
        id: Surrogate primary key.
        device_id: Owning device.
        read_at: When the meter reported the value — **UTC, timezone-aware**.
        source: Which acquisition path produced it (``dlms`` / ``modbus``). A
            property of the reading, never a branch in read-path code.
        logger_id: Which load profile the row came from, derived from the
            profile's OBIS (``1.0.99.1.0.255`` → 1, ``1.0.99.2.0.255`` → 2 —
            SPEC §3.5), never from discovery order. Part of the row's identity:
            two loggers on one meter record *separate rows*, not a merge, because
            no CEWE model's loggers can be merged (they differ in period, or map
            different registers onto one column).
        interval_sec: The meter's own capture period for that logger, in seconds
            as it reports them (ProfileGeneric attr 4). Never assumed to be 900 —
            a Prometer 100's Logger 2 is 300.
        volt_l1/volt_l2/volt_l3: Phase-to-neutral voltage (V).
        current_l1/current_l2/current_l3: Line current (A).
        freq: Frequency (Hz). **Empty until M4c**, on the same footing as the
            four below: the SMW110W4's load profile has no frequency column, so
            the driver hard-sets it to None, while a Prometer 100 captures it in
            both loggers (SPEC §3.5). Easy to miss because it is not one of the
            "four added columns" §3.5 names — five of the twelve are empty in
            service, not four.
        import_active_kwh: Active energy import — **kWh**, already divided down
            from the meter's raw Wh by the driver.
        import_reactive_kvarh/export_active_kwh/export_reactive_kvarh/avg_geo_pf:
            The rest of the twelve-column set the v1 Load Profile page shows
            (SPEC §3.5). **Empty until M4c** — the SMW110W4 does not capture
            them; all three CEWE models do.
        created_at: When this row was written (UTC).
    """

    __tablename__ = "load_profile_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(16))
    # The server defaults exist so migration 0006's ALTER could not fail on a
    # non-empty table, and are declared here too so the schema on disk and this
    # model agree (0005's docstring: that drift must never be allowed). No
    # writer relies on them — every row supplies both values explicitly.
    logger_id: Mapped[int] = mapped_column(Integer, server_default="1")
    interval_sec: Mapped[int] = mapped_column(Integer, server_default="900")

    volt_l1: Mapped[float | None] = mapped_column(default=None)
    volt_l2: Mapped[float | None] = mapped_column(default=None)
    volt_l3: Mapped[float | None] = mapped_column(default=None)
    current_l1: Mapped[float | None] = mapped_column(default=None)
    current_l2: Mapped[float | None] = mapped_column(default=None)
    current_l3: Mapped[float | None] = mapped_column(default=None)
    freq: Mapped[float | None] = mapped_column(default=None)
    import_active_kwh: Mapped[float | None] = mapped_column(default=None)
    import_reactive_kvarh: Mapped[float | None] = mapped_column(default=None)
    export_active_kwh: Mapped[float | None] = mapped_column(default=None)
    export_reactive_kvarh: Mapped[float | None] = mapped_column(default=None)
    avg_geo_pf: Mapped[float | None] = mapped_column(default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    device: Mapped[Device] = relationship(back_populates="readings")

    __table_args__ = (
        # Load Profile's page query (M5): one device's rows over a date range.
        Index("ix_load_profile_readings_device_read_at", "device_id", "read_at"),
        # The row's real identity (SPEC §3.5, ADR 0008). It is what makes the
        # job's deliberate re-read of the watermark row an upsert instead of a
        # duplicate.
        UniqueConstraint("device_id", "logger_id", "read_at", name="uq_load_profile_readings_device_logger_read_at"),
    )


class DeviceEvent(Base):
    """One row recorded when something about a device *changes* (M3-2).

    CONTEXT.md — Device Event: *"One row recorded when something changes: a
    status transition, or an operator action (created, updated, paused, resumed,
    data cleared) with the name of who did it. Not a per-tick heartbeat — a meter
    that stays online all month writes no rows."*

    That is why there is no ``device_heartbeats`` table in v2 (ADR 0004): at 30
    meters a per-tick row would be 43,200 rows a day that nobody reads, while
    transitions alone answer both operator questions ("what is down now", "when
    did it drop").

    Attributes:
        id: Surrogate primary key.
        device_id: Owning device. The row goes when the device does.
        kind: What happened — the values of
            :class:`arichds.acquisition.status.DeviceEventKind`. A plain string
            column for the same cycle reason :attr:`Device.status` is.
        detail: A sentence for a person, or None.
        actor: The username that caused it, or **None for an automatic
            transition** — nobody changed the device, the meter changed state.
        created_at: When it was recorded (UTC).
        device: The owning device.
    """

    __tablename__ = "device_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str | None] = mapped_column(String(255), default=None)
    actor: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    device: Mapped[Device] = relationship(back_populates="events")

    __table_args__ = (
        # The History drawer's only query: this device's events, newest first.
        Index("ix_device_events_device_created_at", "device_id", "created_at"),
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
