# 0026. Modbus stays in its own Go program — ARICHDS v2 reads DLMS/COSEM only

**Status:** Accepted · 2026-09-18 · owner decision, in the owner's words: *"m4b ไม่ต้องมีแล้ว
ฉันมีโปรแกรม modbus ที่ใช้ golang แยกต่างหาก"* (M4b is no longer needed; I have a separate Modbus
program written in Go).

**Reverses:** `docs/REMAKE-PLAN.md` decision **D1** ("merge Modbus by porting the Go program to
Python", §3.1) and the `SPEC.md` §2 goal *"1 process · 1 exe · 1 database · 1 license covering
both DLMS and Modbus"*. **Closes:** SPEC §5's two Modbus open questions (the Modbus→COSEM
mapping and the fate of the Modbus billing cut).

## Context

v1 ran two services in two languages: the Python DLMS worker and `modbus-logger` (Go, ~4.4k
lines, its own database and its own activation). The remake planned to port the Go program into
Python behind the same `MeterDriver` (milestone **M4b**, days 6–14). That plan mapped Modbus
registers onto COSEM columns at write time (REMAKE-PLAN §6.1). It also left one question for the
M4b grill: whether to keep the Modbus billing cut. That cut is a period close the *system*
performs, and it conflicts with the owner's rule that this product only reads a meter
(grill M6, 2026-08-09).

M4b never started. On 2026-09-18 there is no Modbus code in v2: `pymodbus` is not a dependency,
there is no Modbus driver, and the only traces are the constant `SOURCE_MODBUS` and the
documented `modbus` value of the `source` column. The owner keeps a separate Go program for
Modbus and does not want it merged.

## Decision

1. **ARICHDS v2 reads meters over DLMS/COSEM only.** M4b is removed from the plan. There will be
   no Modbus driver, no `pymodbus`, no register→COSEM mapping and no raw-register safety-net table.
2. **The Modbus billing cut is not this program's concern.** The conflict it raised with the
   read-only invariant is closed by not owning the feature.
3. **No integration with the Go program.** v2 does not read its database, list its meters, or
   push or upload its data. *This point is the implementer's stated assumption, not a grilled
   answer.* Revisit it the first time a site needs one UI, one push or one upload covering both
   programs.

## Consequences

- **Model coverage is unchanged.** All 9 catalogued models already have a DLMS driver: SMW110
  over DLMS serial and TCP, and Prometer 100 over DLMS TCP. What leaves scope is the Modbus
  *protocol*: a meter reachable only over Modbus belongs to the Go program.
- **A site with Modbus meters runs two programs with two licences again.** That brings back v1's
  "two services" pain point, by choice and only for those sites. REMAKE-PLAN D8 records that
  Modbus is a very small minority of the installed base.
- **The three Data-out Destinations carry only what v2 reads.** Nothing from the Go program
  reaches the Central Push, the File Upload Destination or the Database Destination.
- **The `source` column and `SOURCE_MODBUS` stay.** Dropping the column would cost a migration
  and buy nothing. The only value any code writes is `dlms`; `modbus` remains a reserved value
  that no code writes. Do not add read-path branches on `source`: it was always data, never
  control flow.
- **The plan's Modbus sections stay in the documents as history.** They are REMAKE-PLAN §3.1,
  the Modbus half of §6.1 and M4b, marked as reversed by this ADR. Do not read them as work
  still to do.
