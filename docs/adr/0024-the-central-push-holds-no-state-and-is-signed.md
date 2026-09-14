# The central push holds no state, and is signed with a Push Token

Status: accepted (2026-09-14, owner decision during the M14 grill — customer requirement E4).
Settles SPEC §3.8's open question on the field-level contract and on how the server verifies a
token. Partially implemented: M14 ticket 03 landed the Push Token issue/verify primitive, and
ticket 07 landed the configuration, the admin endpoints and the published contract (see
CLAUDE.md's digest for both). The push cycle itself — the scheduler job, the holdings/push HTTP
client, and everything that writes `centralpush/status.py` — is ticket 08, still unbuilt.

The customer's requirement E4 is one word — `"API"`, sheet 13, cell P17 — which the owner has
confirmed means ARICHDS pushes outward. v1 has **no data push to copy**: its only outbound HTTP is
licensing (`/renew`, `/redeem`, `/activate`), whose bodies never carry a reading, and v1's ADR 0006
deferred exactly this work for want of a real consumer. So there is no Output Parity anchor, only
v1's *data* to match.

## The decision

- **What**: Billing, Load Profile, the Energy Summary (ADR 0022) and the meter roster with its
  status, to the team's own server as JSON every fifteen minutes, outbound HTTPS only.
- **Whose contract**: **ours**, versioned, and published on the in-app **API** page — rendered
  from the same models that serialize the payload, so the published spec cannot drift from what
  is sent. The receiving team implements to it. The same page holds the server URL, the Push
  Token and the last cycle's status.
- **No state on our side.** Each cycle starts by asking the server what it holds: the newest
  `read_at` per Meter Serial and logger for Load Profile; the newest `updated_at` per Meter Serial
  for Billing and the Energy Summary. The roster is a full snapshot every cycle. That query
  endpoint is part of the published contract. **`sync_state` is not built.**
- **Identity**: a meter is its **Meter Serial**, never `device_id`, which is a SQLite rowid reused
  after a delete and collides across sites. Times are **ISO 8601 with an explicit offset**.
- **Auth — the Push Token**: a JWT signed **EdDSA** with the vendor's existing Ed25519 key, issued
  by a new `tools/arichds_vendor.py` subcommand, carrying the Machine ID and a claim of its own
  that makes it impossible to accept as an Activation Code, or an Activation Code as it. The
  server verifies with the public key and keeps a denylist by Machine ID for revocation.
  **Never run `keygen`**: a new pair would invalidate every licence already issued.
- **Failure**: connect and read timeouts, a per-cycle time budget, last in the scheduler queue; an
  unreachable server means the cycle is skipped. Status lives in memory, as `dataout/status.py`
  does. There is no offline queue — the next cycle asks again and converges.
- **Opting out**: a site with no URL configured sends nothing. The one site whose customer refuses
  cloud upload keeps Syncthing; there is no licence key and no second switch.
- **Retention on the server**: it keeps everything. Rows older than our 90-day window stay at the
  value last pushed, because we no longer hold the readings to recompute them — and the published
  spec says so.

## Considered

| Rejected | Why |
|---|---|
| A `sync_state` watermark table (REMAKE-PLAN §3.5) | Designed before ADR 0008, which forbids persisted job state; the Database Destination (SPEC §3.10) already proved that asking the destination works and heals itself |
| The Activation Code as the bearer credential | It is not a secret — operators paste it by hand — so anyone who has seen it could push as that site |
| A token issued by the portal at online activation | Ties M8 to M9 and to a portal v2 that has no timeline |
| A shared HMAC secret per site | A secret to distribute and store on both ends, where a public key needs neither |
| A per-machine keypair certified by the vendor | No bearer secret at all, but the most work for a threat the denylist already answers |
| Leaving the contract for the server team to define | The payload shapes are ours, and the server must add an endpoint either way |

## Consequences

- The receiving team must build **two** endpoints: accept a push, and answer what it holds.
- A Billing row or an Energy Summary row can change after it was sent, so the server must
  **upsert**, keyed on Meter Serial plus the row's natural key, never append.
- SPEC §4's table list loses `sync_state`; with ADR 0022's two tables the schema reaches 12.
