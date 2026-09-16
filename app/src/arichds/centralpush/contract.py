"""Contract version 1 — the payload shapes Central Push sends, and the
document rendered from them for the API page (ADR 0024, "Contract version
1"; CONTEXT.md — Central Push).

**Ours, published, generated.** The receiving team implements to the exact
thing the machine sends, so the four item kinds below (:data:`ITEM_KINDS`)
are the one place their fields are declared — :func:`render_contract` lists
every field a model declares by walking ``model_fields``, never a
hand-written duplicate list, so a field added to a model appears in the
published contract with no other edit.

``LoadProfileItem`` and ``BillingItem``'s measurement columns are built by
:func:`_measurement_fields` straight off
:class:`arichds.db.models.LoadProfileReading` /
:class:`arichds.db.models.BillingReading` rather than typed out by hand —
the acceptance criterion here is literally "every measured column", twelve
and sixty of them respectively, and the ORM model is the one place that
list cannot go stale.

Ticket 07 defines these payload shapes and renders the contract; it never
sends one. Building and sending an envelope is ticket 08.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, Field, create_model

from arichds.acquisition.status import DeviceStatus
from arichds.db.models import BillingReading, EnergySummaryDay, LoadProfileReading

#: The one contract version this build speaks (ADR 0024). A future change
#: bumps this and is a new, additively-named version — never a silent
#: reshape of the fields below.
CONTRACT_VERSION: Final[int] = 1

_HOLDINGS_PATH: Final[str] = "/v1/holdings"
_PUSH_PATH: Final[str] = "/v1/push"

ItemKind = Literal["meters", "billing", "energy_summary", "load_profile"]


# ─── Item kinds ─────────────────────────────────────────────────────────────


def _measurement_fields(orm_model: type, exclude: frozenset[str]) -> dict[str, tuple[Any, Any]]:
    """Every column of *orm_model*, except *exclude*, as a Pydantic field spec.

    Reads nullability and the Python type straight off the SQLAlchemy
    column — every measurement column in both source tables is declared
    nullable, so this always produces an optional field defaulting to
    ``None``, but the branch below also covers a future non-nullable
    measurement column correctly rather than assuming one never arrives.
    """
    fields: dict[str, tuple[Any, Any]] = {}
    for column in orm_model.__table__.columns:
        if column.name in exclude:
            continue
        python_type = column.type.python_type
        description = f"Measured column {column.name!r} — not every meter model populates every column."
        if column.nullable:
            fields[column.name] = (python_type | None, Field(default=None, description=description))
        else:
            fields[column.name] = (python_type, Field(description=description))
    return fields


#: Bookkeeping/identity columns of `LoadProfileReading` handled explicitly
#: below rather than picked up as "measured" — `meter_serial` is not even a
#: column there (it lives on `Device`; a push item joins it in).
_LOAD_PROFILE_EXCLUDE: Final[frozenset[str]] = frozenset(
    {"id", "device_id", "read_at", "source", "logger_id", "interval_sec", "interval_status_flag", "created_at"}
)

LoadProfileItem = create_model(
    "LoadProfileItem",
    __doc__="One Interval Reading (SPEC §3.5, CONTEXT.md — Interval Reading).",
    meter_serial=(str, Field(description="Natural key 1/3 — never `device_id`, a SQLite rowid reused after a delete.")),
    logger_id=(int, Field(description="Natural key 2/3 — which load profile logger produced the row (1 or 2).")),
    read_at=(
        datetime,
        Field(description="Natural key 3/3 — ISO 8601 with the site's UTC offset, when the meter reported the value."),
    ),
    interval_sec=(int, Field(description="The meter's own capture period for this logger, in seconds.")),
    interval_status_flag=(
        int | None,
        Field(
            default=None,
            description="The meter's own Interval Status word. Bit 0 set means the interval is all-invalid.",
        ),
    ),
    **_measurement_fields(LoadProfileReading, _LOAD_PROFILE_EXCLUDE),
)

#: `meter_serial` and `updated_at`/`bill_date` are handled explicitly below —
#: `record_status` becomes `is_open`, a clearer boolean for a receiver that
#: never sees the string encoding this store uses internally.
_BILLING_EXCLUDE: Final[frozenset[str]] = frozenset(
    {
        "id",
        "device_id",
        "bill_date",
        "read_at",
        "record_status",
        "source",
        "meter_serial",
        "created_at",
        "updated_at",
        # Bookkeeping about this machine's capture folder (ui-audit ticket 03),
        # not a measurement — contract version 1 must not grow a field for it.
        "captured_at",
    }
)

BillingItem = create_model(
    "BillingItem",
    __doc__="One Billing Reading (SPEC §3.6, CONTEXT.md — Billing Reading).",
    meter_serial=(str, Field(description="Natural key 1/2.")),
    bill_date=(
        datetime,
        Field(
            description="Natural key 2/2 — ISO 8601 with the site's UTC offset, the meter's own Clock cell for this period."
        ),
    ),
    is_open=(
        bool,
        Field(
            description="True for the one Open Period slot a device may hold; false for a closed period. Re-sent whenever it changes."
        ),
    ),
    updated_at=(
        datetime,
        Field(
            description="ISO 8601 with the site's UTC offset, like every other instant. Re-sent whenever any field on this row changes."
        ),
    ),
    **_measurement_fields(BillingReading, _BILLING_EXCLUDE),
)

_ENERGY_SUMMARY_EXCLUDE: Final[frozenset[str]] = frozenset({"id", "device_id", "local_date", "updated_at"})

EnergySummaryItem = create_model(
    "EnergySummaryItem",
    __doc__="One meter's Time-of-Use split for one local day (ADR 0022, CONTEXT.md — Energy Summary).",
    meter_serial=(str, Field(description="Natural key 1/2.")),
    local_date=(date, Field(description="Natural key 2/2 — a plain date, the site's local calendar day, never UTC.")),
    updated_at=(
        datetime,
        Field(
            description="ISO 8601 with the site's UTC offset, like every other instant. Re-sent whenever a bucket value changes — a Holiday edit or a late reading."
        ),
    ),
    **_measurement_fields(EnergySummaryDay, _ENERGY_SUMMARY_EXCLUDE),
)


class MeterItem(BaseModel):
    """One meter and its status (SPEC story 19)."""

    meter_serial: str = Field(
        description="Natural key. The roster replaces the machine's whole set every cycle, never upserted by it."
    )
    device_name: str = Field(description="Operator-facing device name.")
    brand: str = Field(description="Meter brand, e.g. 'cewe'.")
    model: str = Field(description="Meter model key.")
    status: DeviceStatus = Field(description="One of online / offline / unknown / paused.")


#: Every item kind's model, keyed by the `kind` value it travels under in a
#: :class:`PushEnvelope`. The one place :func:`render_contract` reads to
#: build the published document — parameterised there (not a bare module
#: reference) precisely so a test can substitute a model carrying an extra
#: field and observe the render pick it up, without mutating these real ones.
ITEM_KINDS: Final[Mapping[ItemKind, type[BaseModel]]] = {
    "meters": MeterItem,
    "billing": BillingItem,
    "energy_summary": EnergySummaryItem,
    "load_profile": LoadProfileItem,
}

#: The natural key the server upserts on for each kind (ADR 0024). `meters`
#: is not upserted by one — the roster is a full replace — but its Meter
#: Serial is still the identifying field, so it is listed the same way.
NATURAL_KEYS: Final[Mapping[ItemKind, tuple[str, ...]]] = {
    "load_profile": ("meter_serial", "logger_id", "read_at"),
    "billing": ("meter_serial", "bill_date"),
    "energy_summary": ("meter_serial", "local_date"),
    "meters": ("meter_serial",),
}


# ─── Holdings / envelope ────────────────────────────────────────────────────


class HoldingsLoadProfileEntry(BaseModel):
    meter_serial: str = Field(description="Which meter this holding is for.")
    logger_id: int = Field(description="Which load profile logger this holding is for (1 or 2).")
    newest_read_at: datetime = Field(
        description="The newest `read_at` the server holds for this meter/logger — ISO 8601 with the site's UTC offset."
    )


class HoldingsBillingEntry(BaseModel):
    meter_serial: str = Field(description="Which meter this holding is for.")
    newest_updated_at: datetime = Field(
        description="The newest `updated_at` the server holds among this meter's billing rows — ISO 8601 with the site's UTC offset."
    )


class HoldingsEnergySummaryEntry(BaseModel):
    meter_serial: str = Field(description="Which meter this holding is for.")
    newest_updated_at: datetime = Field(
        description="The newest `updated_at` the server holds among this meter's Energy Summary rows — ISO 8601 with the site's UTC offset."
    )


class HoldingsResponse(BaseModel):
    """``GET {server_url}/v1/holdings`` — what the receiving server already
    holds, so the machine sends only what is missing or changed (ADR 0024:
    "No state on our side"). A meter the server has never seen is simply
    absent from the relevant list.
    """

    contract_version: int = Field(description="The contract version this holdings answer was built for.")
    load_profile: list[HoldingsLoadProfileEntry] = Field(
        default_factory=list,
        description="One entry per (meter, logger) the server has ever received a load-profile row for.",
    )
    billing: list[HoldingsBillingEntry] = Field(
        default_factory=list, description="One entry per meter the server has ever received a billing row for."
    )
    energy_summary: list[HoldingsEnergySummaryEntry] = Field(
        default_factory=list, description="One entry per meter the server has ever received an Energy Summary row for."
    )


class PushEnvelope[ItemT](BaseModel):
    """``POST {server_url}/v1/push`` — one request, one kind of item."""

    contract_version: int = Field(description="The contract version this push was built for.")
    machine_id: str = Field(description="The sending machine's Machine ID — the `sub` claim of its Push Token.")
    sent_at: datetime = Field(description="When this request was built — ISO 8601 with the site's UTC offset.")
    kind: ItemKind = Field(description="Which of the four item kinds `items` holds.")
    items: list[ItemT] = Field(description="The rows themselves — one of the four item kinds named by `kind`.")


#: The three holdings entry kinds, keyed by the `HoldingsResponse` field name
#: they travel under — the same substitutable-mapping shape :data:`ITEM_KINDS`
#: is, and for the same reason: a test can pass a different mapping (e.g. one
#: entry replaced by a subclass carrying an extra field) without mutating the
#: real models.
HOLDINGS_ENTRY_KINDS: Final[Mapping[str, type[BaseModel]]] = {
    "load_profile": HoldingsLoadProfileEntry,
    "billing": HoldingsBillingEntry,
    "energy_summary": HoldingsEnergySummaryEntry,
}


# ─── The published document ─────────────────────────────────────────────────


class ContractField(BaseModel):
    name: str
    type: str
    description: str


class ContractKind(BaseModel):
    kind: str
    natural_key: list[str]
    replace_whole_roster: bool
    fields: list[ContractField]


class ContractHoldingsEntry(BaseModel):
    """One of the three lists inside the holdings response — see
    :data:`HOLDINGS_ENTRY_KINDS`."""

    kind: str
    fields: list[ContractField]


class Contract(BaseModel):
    """The whole published document — what ``GET
    /api/settings/central-push/contract`` returns and the API page renders.

    **Every payload model is walked, not just the four item kinds** — a
    field added to `HoldingsResponse`, one of its three entry models, or
    `PushEnvelope` must appear here too, with no other edit, the same
    guarantee :attr:`kinds` gives the four item models.
    """

    contract_version: int
    holdings_endpoint: str
    push_endpoint: str
    holdings: list[ContractField]
    holdings_entries: list[ContractHoldingsEntry]
    envelope: list[ContractField]
    kinds: list[ContractKind]
    notes: list[str]


def _readable_type(annotation: Any) -> str:
    """A human-readable rendering of a Pydantic field annotation.

    Documentation text only — nothing parses this back, so a simple string
    clean-up is enough: strip Python's `<class '...'>` wrapper, spell
    `datetime.datetime`/`datetime.date`/`NoneType` the way a reader expects,
    and strip this module's own dotted path off a nested model reference
    (`list[arichds.centralpush.contract.HoldingsLoadProfileEntry]` otherwise
    leaks a Python import path to a receiving team that is not Python).
    `typing.Literal[...]` becomes `one of [...]` for the same reason.
    `list[ItemT]` (`PushEnvelope`'s own unparametrised `items` field) is left
    as is — it already reads as "a list of the item type named by `kind`".
    """
    text = str(annotation)
    text = text.replace("<class '", "").replace("'>", "")
    text = text.replace("datetime.datetime", "datetime").replace("datetime.date", "date")
    text = text.replace("NoneType", "null")
    text = text.replace(f"{__name__}.", "")
    text = text.replace("typing.Literal[", "one of [")
    return text


def _fields_of(model: type[BaseModel]) -> list[ContractField]:
    """Every field *model* declares, walked off ``model_fields`` — never a
    hand-written list, so a field added to *model* appears here automatically.
    """
    return [
        ContractField(name=name, type=_readable_type(info.annotation), description=info.description or "")
        for name, info in model.model_fields.items()
    ]


def render_contract(
    item_kinds: Mapping[str, type[BaseModel]] = ITEM_KINDS,
    *,
    holdings_model: type[BaseModel] = HoldingsResponse,
    holdings_entry_kinds: Mapping[str, type[BaseModel]] = HOLDINGS_ENTRY_KINDS,
    envelope_model: type[BaseModel] = PushEnvelope,
) -> Contract:
    """Build the published contract from *item_kinds* and the other payload
    models — every one of them, not just the four item kinds, so a field
    added to any of them appears here with no other edit.

    Args:
        item_kinds: Defaults to :data:`ITEM_KINDS`, the four real item
            payload models. A test may pass a different mapping — e.g. one
            entry replaced by a subclass carrying an extra field — to prove
            the render is generic rather than a duplicated field list,
            without mutating the real models.
        holdings_model: Defaults to :class:`HoldingsResponse`. Same
            substitution point as *item_kinds*.
        holdings_entry_kinds: Defaults to :data:`HOLDINGS_ENTRY_KINDS`, the
            three lists inside a holdings response. Same substitution point.
        envelope_model: Defaults to :class:`PushEnvelope`. Same substitution
            point.

    Returns:
        The document the ``/contract`` endpoint serves and the API page
        renders read-only.
    """
    kinds = [
        ContractKind(
            kind=kind,
            natural_key=list(NATURAL_KEYS.get(kind, ())),
            replace_whole_roster=(kind == "meters"),
            fields=_fields_of(model),
        )
        for kind, model in item_kinds.items()
    ]
    holdings_entries = [
        ContractHoldingsEntry(kind=kind, fields=_fields_of(model)) for kind, model in holdings_entry_kinds.items()
    ]
    return Contract(
        contract_version=CONTRACT_VERSION,
        holdings_endpoint=f"GET {{server_url}}{_HOLDINGS_PATH}",
        push_endpoint=f"POST {{server_url}}{_PUSH_PATH}",
        holdings=_fields_of(holdings_model),
        holdings_entries=holdings_entries,
        envelope=_fields_of(envelope_model),
        kinds=kinds,
        notes=[
            "Every row is identified by Meter Serial, never `device_id` (a SQLite rowid reused after a delete).",
            "Energy is always kWh/kvarh, voltage V, current A — never the machine's own display-unit setting.",
            "Every instant carries the site's UTC offset (ISO 8601); `local_date` is a plain date, not a timestamp.",
            "`interval_status_flag` bit 0 set means the interval is all-invalid.",
            f"`GET {{server_url}}{_HOLDINGS_PATH}` answers what the server already holds — the newest `read_at` "
            "per meter/logger for load profile, and the newest `updated_at` per meter for billing and the "
            "Energy Summary — so the machine sends only rows missing or changed since that answer.",
            f"`POST {{server_url}}{_PUSH_PATH}` accepts one `kind` of item per request, capped per request by a "
            "constant; any 2xx response means the items were accepted.",
            "Every request carries `Authorization: Bearer <Push Token>`.",
            "Rows older than the machine's 90-day retention window are never sent again once they have been "
            "sent — the server's copy of them is final.",
            "`meters` replaces the whole roster every cycle; it is not upserted by its natural key the way the "
            "other three kinds are.",
        ],
    )
