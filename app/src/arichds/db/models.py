"""SQLAlchemy 2 models — M1 tables only.

The full v2 schema is 13 tables (SPEC §4); M1 lands the two that the walking
skeleton needs. The rest arrive module by module, each via its own Alembic
migration — never by widening this file speculatively.

``interval_readings`` is deliberately a *subset* of the COSEM shape defined in
REMAKE-PLAN §6.1. Its normalization contract is absolute and applies from row
one: **always UTC, always kWh, column names match the unit actually stored**.
The conversion happens in the driver at write time, never at read time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    """Declarative base for every ARICHDS table."""


class Device(Base):
    """A meter configured on this machine.

    ``transport`` is a JSON column holding the Transport Endpoint description —
    ``{"kind": "net", "host": ..., "port": ...}`` for TCP. Keeping it as JSON is
    the v2 consolidation decision (SPEC §4: devices absorbs device_settings /
    device_status / device_capture_objects as JSON columns) and means adding
    serial fields in M3 needs no migration of this column.

    Attributes:
        id: Surrogate primary key.
        name: Operator-facing label, unique per machine.
        brand: Meter brand, e.g. ``"CEWE"`` or ``"SIM"``.
        model: Meter model, e.g. ``"prometer100"`` or ``"SIM"``. Resolves the
            driver via the driver registry.
        transport: Transport Endpoint description (JSON).
        password: DLMS authentication password. Never logged, never returned by
            the API.
        enabled: Whether the Poller should read this device.
        created_at: Row creation time (UTC).
    """

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    brand: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    transport: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    password: Mapped[str] = mapped_column(String(128), default="")
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

    Always UTC, always kWh, regardless of whether the Source was DLMS, Modbus or
    the simulated driver (CONTEXT.md — Interval Reading). M1 stores the
    instantaneous subset: V/I per phase, frequency, and the total import energy
    register.

    Attributes:
        id: Surrogate primary key.
        device_id: Owning device.
        read_at: When the meter reported the value — **UTC, timezone-aware**.
        source: Which acquisition path produced it (``dlms`` / ``modbus`` /
            ``sim``). A property of the reading, never a branch in read-path code.
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
