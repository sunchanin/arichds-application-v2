# Central Push, a stored Energy Summary, and export files that mirror our window (M14)

**Triage**: `ready-for-agent` · **Grilled**: 2026-09-14 · **Decisions**: ADR 0022 · ADR 0023 · ADR 0024 ·
**Requirement**: E4 (`"API"`, sheet 13 P17) · **Record**: `docs/REMAKE-PLAN.md` §7.8

## Problem Statement

**The team's central website cannot get data out of v2.** The customer's full-version
requirements list a data-out called `"API"`, and the owner has confirmed it means ARICHDS
sends data outward. Today the only thing that leaves the machine is the Database Destination,
which writes into the *customer's* MySQL. There is nothing that reaches the team's own server,
v1 never had a data push to copy, and the plan's assumption that a middleman program on the
customer's machine already reads our tables turned out to be unfounded.

**The Energy Summary exists only while a page is rendering it.** It is computed from interval
readings on every request, so nothing else can hold the same numbers: the daily Energy file
freezes whatever it computed that night, and a push would have no rows to track. When an
operator adds a Holiday for a past day, the page changes but the file does not, and the product
answers that with a warning asking the operator to go press a button.

**The export folder grows without end on a machine whose owner said disk space is limited.**
The program deletes load-profile rows after 90 days, but the Load Profile CSV keeps every row it
ever appended, the Energy file was designed as a permanent archive, and every change of column
set leaves another dated copy behind. Purging the database while the folder keeps everything
saves nothing.

## Solution

**An API page.** An administrator enters the team's server URL and a Push Token issued by the
vendor. From then on, every fifteen minutes the machine pushes its billing periods, load
profile, Energy Summary and the list of meters with their status. Each cycle it first asks the
server what it already holds and sends only what is missing or changed, so a machine that was
offline for a day catches up by itself. The page shows how the last cycle went, and publishes
the exact contract the receiving team builds against. A site that never enters a URL sends
nothing.

**The Energy Summary becomes stored rows.** Every cycle recomputes the last 90 days for every
meter. The Energy Summary page, the Energy file and the push all read those same rows, so they
always agree. A Holiday added, edited or deleted — or readings a meter sends late after being
offline — show up in every affected day within fifteen minutes, everywhere at once. Every
Holiday change is recorded with who made it and when.

**Export files keep what the program keeps.** The Load Profile and Energy files hold the last 90
days; the Billing file holds every closed period, because the program never discards billing.
Files are replaced safely in one step, so nothing reading the folder sees half a file, and a
change of column set simply rewrites the file under its new header — no dated copies.

## User Stories

### Pushing to the central server

1. As a site administrator, I want an **API** page, so that everything about sending data to the team's server lives in one place.
2. As a site administrator, I want to enter the central server's URL, so that the machine knows where to send data.
3. As a site administrator, I want to paste a Push Token, so that the server can tell the data really comes from this machine.
4. As a site administrator, I want the Push Token field to be write-only, so that a token saved once cannot be read back off the screen by anyone else.
5. As a site administrator, I want the page to tell me whether a token is saved, so that I know the push is configured without seeing the secret.
6. As a site administrator, I want a token issued for a different machine to be refused when I save it, so that a copy-paste mistake cannot make this machine impersonate another.
7. As a site administrator, I want a malformed or tampered token refused when I save it, so that I find out at setup rather than from a silent failure later.
8. As a site administrator, I want an Activation Code pasted into the Push Token field to be refused, so that confusing the two secrets cannot happen quietly.
9. As a site administrator, I want to clear the URL to stop pushing, so that turning the feature off needs no other switch.
10. As the operator of the one site that refuses cloud upload, I want a machine with no URL configured to send nothing at all, so that our confidentiality rule holds without special configuration.
11. As a site administrator, I want to see when the last push cycle ran, so that I know it is alive.
12. As a site administrator, I want to see whether the last cycle succeeded, was skipped because the server was unreachable, or ran out of time, so that I can tell a network problem from a working push.
13. As a site administrator, I want to see how many rows of each kind the last cycle sent, so that I can tell data is actually flowing.
14. As a site administrator, I want to see how many rows could not be sent because their meter has no known serial, so that a meter that never reported its serial does not silently lose data.
15. As a member of the team's central website, I want billing periods pushed, so that the site can show bills per meter.
16. As a member of the team's central website, I want the still-open billing period pushed and updated as it changes, so that the site shows the current bill, not only closed ones.
17. As a member of the team's central website, I want load-profile intervals pushed, so that the site can chart consumption.
18. As a member of the team's central website, I want the Energy Summary pushed, so that the site shows the same Time-of-Use split the customer sees on the machine.
19. As a member of the team's central website, I want the list of meters and each meter's status pushed every cycle, so that the site knows which meters exist and which are offline.
20. As a member of the team's central website, I want every row identified by Meter Serial, so that rows from different sites never collide.
21. As a member of the team's central website, I want every timestamp to carry its UTC offset, so that nobody has to guess which timezone a value is in.
22. As a member of the team's central website, I want energy in kWh and kvarh always, regardless of the machine's display setting, so that numbers from different sites are comparable.
23. As a member of the team's central website, I want each interval's status word pushed with it, so that the site can decide for itself how to treat an interval the meter flagged invalid.
24. As a member of the team's central website, I want Energy Summary and billing rows re-sent when their values change, so that a Holiday change or a late reading corrects what the site already holds.
25. As a member of the team's central website, I want a machine that was offline to send everything it missed when it comes back, so that the site ends up complete without anyone intervening.
26. As a developer on the receiving team, I want the push contract published on the API page, so that I build against the exact thing the machine sends.
27. As a developer on the receiving team, I want the published contract generated from the same definitions the machine uses to build its payload, so that the documentation cannot drift from reality.
28. As a developer on the receiving team, I want the contract to carry a version, so that a future change can be recognised rather than guessed.
29. As a developer on the receiving team, I want the contract to state the natural key of every kind of row, so that I know what to upsert on.
30. As a developer on the receiving team, I want the contract to state that rows older than the machine's 90-day window will never be sent again, so that I know those rows are final.
31. As a developer on the receiving team, I want the contract to specify the "what do you hold" query, so that the machine can resume from my answer.
32. As a developer on the receiving team, I want to verify a Push Token with a public key alone, so that my server stores no per-site secret.
33. As a developer on the receiving team, I want a token to name its Machine ID, so that I can refuse a revoked machine by keeping a denylist.

### Issuing Push Tokens

34. As the vendor, I want a `sign-push` command in the vendor tool, so that I issue a Push Token for one machine the same way I issue its Activation Code.
35. As the vendor, I want `sign-push` to use the signing key I already have, so that nothing new needs generating, storing or distributing.
36. As the vendor, I want `sign-push` to refuse a malformed Machine ID, so that I cannot issue a token that fits no machine.
37. As the vendor, I want a Push Token that can never pass as an Activation Code, so that a leaked token cannot unlock a licence.

### A stored Energy Summary

38. As an operator, I want the Energy Summary page to show the same numbers it shows today, so that storing the summary changes nothing I can see.
39. As an operator, I want a Holiday I add for a past day to change that day's summary within fifteen minutes, so that I can correct the calendar after the fact.
40. As an operator, I want editing or deleting a Holiday to recalculate the affected day the same way, so that every change behaves alike.
41. As an operator, I want importing Holidays from a CSV file or from the meter to recalculate affected days too, so that bulk changes are not a special case.
42. As an operator, I want readings a meter sends late after being offline to be counted in that day's summary within fifteen minutes, so that a day is not permanently short.
43. As an operator, I want the Holidays page to tell me after a change that the summary will be recalculated within fifteen minutes, so that I know when to look.
44. As an operator, I want intervals the meter marked all-invalid to stay excluded from the summary, so that stored numbers match what v1 reported.
45. As an operator, I want the summary to cover the same 90 days the program keeps readings for, so that it never claims history it cannot back up.
46. As an administrator, I want every Holiday change recorded with who made it, when, and which day it names, so that I can explain why a past day's numbers moved.
47. As an administrator, I want an import recorded as one change with its source and how many Holidays it brought in, so that the record stays readable.
48. As an administrator, I want the Holiday Change record kept for 90 days, so that it lasts exactly as long as the numbers it explains.
49. As any signed-in user, I want to read the Holiday Change record, so that anyone looking at a surprising number can find the reason.

### Export files that mirror the window

50. As a customer with limited disk space, I want the Load Profile CSV to hold only the last 90 days, so that it stops growing.
51. As a customer with limited disk space, I want the Energy file to hold only the last 90 days, so that it stops growing.
52. As a customer, I want the Billing file to keep every closed period, so that no bill disappears from the file while the program still holds it.
53. As a customer, I want the Load Profile CSV to keep receiving new rows every cycle, so that trimming does not delay fresh data.
54. As a customer, I want old Load Profile rows removed at most once a day, so that the file is not rewritten every fifteen minutes.
55. As a customer, I want the Energy file to always match the Energy Summary page, so that I never have to wonder which is right.
56. As a customer, I want a file replaced in one step, so that my own tools and Syncthing never read a half-written file.
57. As a customer, I want a change of column set to rewrite the file under the new header, so that my folder does not collect dated copies.
58. As a customer, I want each file to carry exactly one header, so that every row in it matches the header above it.
59. As a customer, I want the auto-save switch to keep governing all three files, so that turning it off still stops every file.
60. As an operator, I want **Save to file** on the Energy Summary page to keep saving the range I pick into its own file, so that I can still take a snapshot of any period.
61. As a customer using Syncthing to mirror the folder, I want to know the mirror also holds only 90 days, so that I keep my own copy if I need longer history.

## Implementation Decisions

### Scheduler order

The job registry becomes, in order: load profile → **Energy Summary recompute** → CSV export →
billing → battery → backup → retention → Database Destination sync → **Central Push**. The
recompute runs immediately after the load-profile read so every export and the push read fresh
rows. The Central Push is last because it is the second job that talks to a machine we do not
own, and jobs share one thread.

### Energy Summary store (ADR 0022)

- **New table `energy_summary_days`**: device, local calendar date (a plain date — Time-of-Use
  days are local days), the eight buckets (Peak, Off-Peak, Holiday and Total, each for import and
  export active energy), and `updated_at` (UTC). Unique on device plus local date. Rows cascade
  with their device.
- **Recompute job, every load-profile cycle**: for every device, compute the whole window from
  `local_today − (RETENTION_DAYS − 1)` to `local_today` with the **existing** Time-of-Use
  aggregation, unchanged — Logger 1 only, weekends and both Holiday kinds as Holiday, the constant
  peak window, and the all-invalid exclusion. Upsert each day. **`updated_at` changes only when a
  bucket value actually differs**; a recompute that finds nothing new writes nothing. A day with
  no readings produces no row.
- **Measured cost** (a copy of the install database, 4 meters, 96,017 rows, a full 90 days): about
  0.07 s per meter for the whole window, independent of how many Holidays exist. The largest site
  the owner has seen has under 20 meters.
- **`GET /api/energy/summary` keeps its contract**, including the 31-day request bound; only its
  source changes, from the live aggregation to the table.
- **Retention** deletes stored days older than `RETENTION_DAYS`.

### Holiday Change record (ADR 0022)

- **New table `holiday_changes`**: when (UTC), who (username), action — `add`, `edit`, `delete`,
  `import_csv`, `import_meter` — the Holiday's kind, name and day (date, or month and day) for the
  three single-row actions, and a count for the two imports. Written **in the same transaction**
  as the Holiday mutation on all five endpoints, and also logged to the App Log.
- **Retention** deletes changes older than `RETENTION_DAYS`.
- **New read endpoint** under the Holidays API, available to any signed-in role, newest first.
- **The Holiday mutation response drops** `affected_date` and `energy_files_written_past`, and the
  helpers that computed them are removed. The Holidays page replaces M13 issue 03's stale-file
  warning with a notice that the Energy Summary will be recalculated within fifteen minutes.

### Export files (ADR 0023)

- **The shared writer gains one primitive: atomic whole-file replacement** — write the complete
  file (BOM, header block, header row, rows) to a temporary file in the same directory, flush and
  sync it, then replace the target in one operation. On any failure the previous file is left
  exactly as it was and the temporary file is removed.
- **Closed Editions are removed.** When an existing file's head differs from the head we would
  write today, the writer rewrites the whole window under the current head instead of renaming the
  file. The rename path is deleted. Dated files already on a disk are not touched; M13 never
  reached the customer, so none exist there.
- **Load Profile CSV**: appends each cycle exactly as today — same merged Logger 1/Logger 2 rows,
  same skew cap, same all-invalid exclusion, same `csv_exported_through` watermark. **At most once
  per local day**, when the oldest row in the file has fallen outside the 90-day window, the file
  is rewritten from the same merged-row query over the window and the watermark set to the newest
  row written. A rewritten file must equal what appending would have produced for those days. The
  file therefore holds at most 91 days.
- **Energy file**: rewritten whole **every export cycle** from `energy_summary_days` for the last
  90 days, keeping its 9-column layout and header block. `devices.energy_exported_through` is no
  longer needed and is dropped.
- **Billing file**: rewritten whole **every export cycle** with every closed period, keeping its 24
  columns, `Record No` ordinal and header block. The Open Period stays excluded.
  `devices.billing_exported_through` is dropped.
- **Save to file** keeps writing the chosen range to its own range-named file, now read from the
  table.
- **The auto-save switch, output folder, filename templates and date format** govern all three
  files unchanged.

### Central Push (ADR 0024)

- **A new module, separate from the Database Destination.** They are two transports with two
  contracts (SPEC §3.10); the push shares no code with it, though it follows the same patterns:
  settings rows, a status record held in memory, a per-cycle time budget, last in the queue.
- **Settings**: the server URL, and the Push Token stored write-only — never returned by any
  endpoint, and covered by the credential redaction filter. An empty URL means the cycle does
  nothing and makes no request.
- **Endpoints (admin only, no licence feature key)**: read and update the configuration (the
  response carries the URL and whether a token is set, never the token); read the last cycle's
  status; read the published contract.
- **Saving a token verifies it on the machine**: a valid EdDSA signature under the compiled-in
  vendor public key, the Push Token product claim, a supported token version, and a Machine ID
  claim equal to this machine's own. Anything else is refused with a message saying which check
  failed.
- **Push Token format**: a JWT signed `EdDSA` with the existing vendor Ed25519 key. Claims: `sub`
  (the Machine ID), `product` = `arichds-push` (the licence uses `arichds`), `v` (token version, 1)
  and `iat`. **No expiry** — revocation is the receiving server's denylist by Machine ID. The
  licence and Meter Activation Code verifiers refuse anything carrying `arichds-push`, and the
  Push Token verifier refuses anything that is not a JWT with that product.
- **Vendor tool**: a `sign-push --machine-id <64-hex>` subcommand that prints one token line. It
  loads the existing private key exactly as `sign` does, and like `sign`, it never generates a key.
- **HTTP client**: the standard library's `urllib`, as v1's licence renewal client chose — no new
  runtime dependency and nothing new for PyInstaller to collect. Every request carries
  `Authorization: Bearer <Push Token>`, explicit connect and read timeouts, and a JSON body.
- **Cycle**, when a URL is configured:
  1. Ask the server what it holds.
  2. Send the meter roster as a full snapshot.
  3. Send billing rows whose `updated_at` is newer than the server's newest for that Meter Serial.
  4. Send Energy Summary rows the same way.
  5. Send load-profile rows newer than the server's newest `read_at` for that Meter Serial and
     logger, rewound by a small safety margin (the server upserts, so an overlap is harmless).
  6. Stop at the cycle's time budget; the next cycle resumes from the server's answer.

  An unreachable server, a timeout or a non-2xx response ends the cycle as skipped. There is no
  retry within a cycle and no offline queue. Status (ran at, outcome, rows sent per kind, rows
  skipped for lack of a Meter Serial, error class) lives in memory and resets on restart.
- **Only licensed kinds are sent**: billing needs `billing`, load profile `load_profile`, and the
  Energy Summary `energy_summary`. The roster is always sent.
- **Rows whose device has no known Meter Serial are not sent**, and are counted in status.

### Contract version 1

Published on the API page, rendered from the same payload definitions the push serializes.

- **`GET {url}/v1/holdings`** → `contract_version`; `load_profile`: list of `meter_serial`,
  `logger_id`, `newest_read_at`; `billing`: list of `meter_serial`, `newest_updated_at`;
  `energy_summary`: list of `meter_serial`, `newest_updated_at`. A meter the server has never seen
  is simply absent.
- **`POST {url}/v1/push`** with `contract_version`, `machine_id`, `sent_at`, `kind` — one of
  `meters`, `billing`, `energy_summary`, `load_profile` — and `items`, capped per request by a
  constant. Any 2xx means accepted.
- **Natural keys the server upserts on**: load profile `(meter_serial, logger_id, read_at)`;
  billing `(meter_serial, bill_date)`; Energy Summary `(meter_serial, local_date)`. `meters`
  replaces the machine's whole roster.
- **Items**:
  - load profile — `meter_serial`, `logger_id`, `read_at`, `interval_sec`, every measured column
    under its COSEM column name, and `interval_status_flag` with bit 0 documented as all-invalid.
  - billing — `meter_serial`, `bill_date`, `is_open`, `updated_at`, and every billing measurement
    column.
  - Energy Summary — `meter_serial`, `local_date`, the eight buckets and `updated_at`.
  - meters — `meter_serial`, device name, brand, model, and `status` ∈ `online`, `offline`,
    `unknown`, `paused`.
- **Values**: instants are ISO 8601 with the site's UTC offset; `local_date` is a plain date;
  energy is always kWh/kvarh, voltage V, current A — never a display unit.
- **Stated in the contract**: rows older than the machine's 90-day window are never sent again,
  so the server's copy of them is final; the server keeps everything it receives.

### Web

- **An `API` page** under Data-out, admin only, visible regardless of licence features: a
  configuration form (URL, write-only Push Token with a "token set" indicator), a status card for
  the last cycle, and a read-only view of the published contract. English only.
- **Holidays page**: the new recalculation notice and a view of the Holiday Change record.
- **Energy Summary page**: unchanged.

### Schema

One migration: create `energy_summary_days` and `holiday_changes`; drop
`devices.billing_exported_through` and `devices.energy_exported_through`. The schema goes from 10
tables to 12. `sync_state` is not created.

## Testing Decisions

**A good test here observes behaviour at one of three seams, never an internal step.** Every
acceptance test is written so that removing or weakening the behaviour it names turns it red, and
the implementer probes that by mutation, as this repo has done for the last several phases. Tests
never touch the real vendor private key: they generate an ephemeral Ed25519 pair and point the
public-key loader at it.

### Seam 1 — the HTTP API

- **Stored, not live**: recompute, delete the underlying load-profile rows, and
  `GET /api/energy/summary` still returns the same numbers.
- **Output Parity with today**: for the same seeded readings and Holidays, the stored rows equal
  what the current live aggregation returns, day by day and bucket by bucket.
- **Retroactive**: a Holiday added through the API for a past day moves that day's energy into
  the Holiday bucket after one recompute; editing, deleting and both imports do the same.
- **Late readings**: rows inserted for a past day after a recompute are counted after the next.
- **Quiet recompute**: a second recompute over unchanged data leaves every `updated_at` untouched.
- **Holiday Change record**: each of the five mutations produces exactly one record with the
  right action, user and day or count, readable by a non-admin.
- **Push configuration**: the token is never returned; a token for another Machine ID, a tampered
  token, a token signed by another key and an Activation Code are each refused with the failing
  check named; clearing the URL disables the push.
- **Published contract**: it lists every field the payload definitions declare, so a field added
  to a definition appears in the contract with no other change.
- Prior art: `test_api_energy.py`, `test_api_holidays.py`, `test_dataout_config_api.py`.

### Seam 2 — the scheduler jobs, observed at their outside edge

**Export files**, run against a temporary output folder and read back from disk:

- **Window**: the Load Profile and Energy files hold only rows inside 90 days; the Billing file
  holds every closed period.
- **Trim cadence**: the Load Profile file is rewritten at most once per local day; between trims
  it only grows by appends.
- **Every-cycle rewrite**: the Energy and Billing files are rewritten every cycle and match the
  table and the billing rows exactly.
- **Head change**: changing the head rewrites the one file in place, and no dated file appears.
- **Atomicity**: a failure injected mid-write leaves the previous file byte-for-byte intact, with
  no temporary file left behind.
- **Switch**: auto-save off writes nothing.
- Prior art: `test_csv_export.py`, `test_energy_csv_export.py`, `test_billing_csv_export.py`.

**Central Push**, against a **fake receiver**: a small HTTP server run in-process on an ephemeral
port that implements contract version 1 — it verifies the Push Token against the test public key,
answers holdings from what it has stored, and records every item. Tests assert only on what the
receiver holds.

- **First and second cycles**: the first sends everything; the second, with nothing changed,
  sends nothing but the roster.
- **Changed rows**: a changed Open Period, or an Energy Summary day moved by a Holiday change, is
  re-sent.
- **Catch-up**: a receiver that lost its data gets everything back on the next cycle.
- **Opt-out**: no URL means the receiver sees no request at all.
- **Failure**: a closed port ends the cycle skipped, with status recorded. A receiver that stalls
  is abandoned within the time budget.
- **Filtering**: an unlicensed kind is not sent; rows without a Meter Serial are not sent and are
  counted.
- **Values**: every instant carries an offset; energy is in kWh whatever the display setting.
- Prior art: `test_dataout_sync.py` for pure pieces, and `test_dataout_mysql.py` as the precedent
  for a test that talks to a real server.

### Seam 3 — the vendor tool

- **`sign-push` round trip**: run through the real `vendor_cli` fixture, it produces a token the
  app verifier accepts for that Machine ID.
- **Domain separation, both ways**: a Push Token is refused by the Activation Code verifier and an
  Activation Code is refused by the Push Token verifier.
- **Bad input**: a malformed Machine ID is refused and nothing is printed.
- Prior art: `test_vendor_sign_features.py`.

### Gates, written into every ticket

`ruff format --check .` + `ruff check .` + `pytest -n auto` in `app/`; `pnpm lint` + `pnpm build`
in `web/`; `test_nav_feature_contract.py` stays green with the new nav entry; **Output Parity** for
the Energy Summary as above. No real-meter read is required — no driver changes.

## Out of Scope

- **The receiving server itself.** It is the team's own project; this delivers the contract and a
  fake receiver that implements it.
- **Online activation, the portal and its machine token (M9).** The Push Token is vendor-signed
  offline.
- **Token expiry, rotation screens or revocation on the machine.** Revocation is the server's
  denylist.
- **The File Upload Destination transport** (FTP/FTPS/SFTP). `file_upload_destination` stays
  reserved and its page stays hidden.
- **The Database Destination.** Its scope stays billing and load profile; the new Energy Summary
  table is not written to the customer's MySQL.
- **An offline queue or in-cycle retry.** The next cycle's holdings query is the retry.
- **Deleting dated files left by M13** on development machines.
- **Sending the customer letter, the build and delivery.**
- **E2 (SMART TCC models), E5 (the seven silent sheets), issues 007 and 019.**

## Further Notes

- **Never run `arichds_vendor.py keygen`**, for any reason, including a missing key during
  `sign-push` work. A new pair invalidates every Activation Code and Meter Activation Code ever
  issued. Find the key; never generate one.
- **M13 has not reached the customer** (their install predates migration 0016). Their first
  upgrade will rewrite the Load Profile CSV under the 25-column head directly, with no dated copy
  ever created.
- **Customer question 3** in `.scratch/export-files/customer-questions.md` asks whether anything
  downstream needs more than 90 days. A "yes" would reopen the scope of ADR 0023, not this
  implementation's mechanics.
- **The receiving team needs two endpoints**, not one: push and holdings. Give them the API page's
  contract before this ships, so the first real cycle has something to talk to.
- **A Syncthing mirror receives the trimmed files** and holds only 90 days too; the customer
  letter says so.
