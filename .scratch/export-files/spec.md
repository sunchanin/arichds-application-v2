# Spec — the export files: billing CSV, Energy Summary file, and eleven Load Profile columns

Grilled 2026-09-09, 37 questions over 8 rounds, with two read-only meter probes run
mid-grill. Phase 3 of the requirements round (`docs/REMAKE-PLAN.md` §7.4 row 3 — M13,
requirements A1/A2/A3/D1). Source briefs: `.scratch/export-file-samples/requirements.md`
and `.scratch/capture-billing-energy/requirements.md`.

**No customer questions remain open on any of the three briefs.**

## Problem Statement

The customer sent four sample files and coloured the additions red. Read together they
say three things the product cannot do today.

**They get no billing file at all.** Every closed billing period is stored, and the
Billing page shows it, but the only thing that reaches disk is a per-period PDF/xlsx
capture. Their downstream work — the PEA energy-management submission — needs one
growing file per meter with a row per period, and today they produce it with a third
Windows-Forms program that we are replacing. Neither v1 nor v2 has ever written this
file.

**They get no Energy Summary file.** The Time-of-Use page shows peak, off-peak and
holiday buckets per day, and there is no control anywhere on it that puts those numbers
into a file. Their note asks for a save button, and for the numbers to be kept the way
Load Profile and Billing readings are kept.

**The Load Profile CSV is eleven columns short of what they asked for.** It exports
fourteen columns; their sample shows twenty-five. Four of the missing eleven are marked
black in their file — meaning they assumed we already produce them — and seven are
marked red. The eleven are: the three average phase angles, the interval status word,
the four average power quantities, and the three line-to-line voltages.

Underneath all three is one problem the product has never had to answer: **an appended
file's header is written once and rows append under it for months.** Adding a column to
such a file is not the same act as adding a column to a screen, and nothing in the
codebase says what happens when the contract changes.

## Solution

Three deliverables, ordered formatter-first so the customer has something usable long
before the driver work lands.

**A billing CSV**, appended, one file per meter, carrying the twenty-four columns of the
customer's own sample and only the periods the meter has actually closed.

**An Energy Summary file**, in two forms that share one layout: a file the scheduler
appends a row to each day, and a file an operator produces on demand for the range they
are looking at. The daily file is a long-term archive — it outlives the ninety-day
retention on the readings it was derived from. The on-demand save is the one corrective
for every reason the archive can be stale.

**Eleven new Load Profile columns**, on the screen and in the file, reaching the file in
the customer's own column order. Every one of the eleven is a value the product already
pulls off the meter every fifteen minutes and discards.

And the rule the three of them share, which is the real deliverable:

> **A file that appends is a contract. When its header changes, the file closes and a
> new one opens — the old file is never rewritten and never receives a row that does not
> match the header it was opened with.**

## User Stories

1. As a site operator, I want one billing file per meter that grows as periods close, so
   that I can hand a single file to the PEA submission instead of opening twelve PDFs.
2. As a site operator, I want that file to hold only periods the meter has actually
   closed, so that a provisional period whose date moves every time we read it never
   appears twice with two different dates.
3. As a site operator, I want a `Record No` that counts from the oldest period, so that
   I can see at a glance whether a period is missing from the middle of the file.
4. As a site operator, I want the billing file to carry the four Export energy columns,
   so that a site that exports power has somewhere to report it.
5. As a site operator, I want demand-time cells that the meter never set to read as a
   dash, so that I can tell "no demand recorded" apart from "a demand recorded on the
   first of January 2000".
6. As a site operator, I want the numbers in the new files to carry four decimals with
   trailing zeros trimmed, so that they look like the files my tooling already reads.
7. As a site operator, I want the customer name, site name and meter serial at the top of
   every file, so that a file that has been copied out of its folder still says which
   meter it came from.
8. As a site operator, I want a Save-now button on the Billing page, so that I can prove
   the output folder is right at install time instead of waiting for the next cycle.
9. As an energy manager, I want the Energy Summary written to a file every day, so that I
   still have the Time-of-Use split after the interval readings behind it have been
   purged.
10. As an energy manager, I want a save button on the Energy Summary page that writes the
    range I am looking at, so that I can produce a corrected file after entering a holiday
    late.
11. As an energy manager, I want the Energy file to have the same columns as the screen
    and no total row, so that I can append several of them or load one into a tool without
    stripping a summary line out of the middle.
12. As an operator entering a holiday, I want to be told when an energy file has already
    written the days I just changed, so that I know to re-save rather than discovering the
    discrepancy in a submission.
13. As an operator entering a holiday for a future date, I want no warning at all, so that
    the warning still means something when it appears.
14. As a site operator, I want the three average phase angles in the Load Profile file, so
    that I can see the phase relationship the meter recorded for each interval.
15. As a site operator, I want the interval status word rendered as words, so that I can
    read which intervals were disturbed without a bit-position legend.
16. As a site operator, I want the four average power columns beside the existing energy
    columns, so that I can see demand and consumption for the same interval in one row.
17. As a site operator, I want the three line-to-line voltages, so that I can see the
    quantity my meter has been recording every five minutes all along.
18. As a site operator, I want the eleven new columns on the Load Profile screen too, so
    that a number that looks wrong in the file can be checked without opening the file.
19. As a site operator, I want the display unit setting to change the power columns on the
    screen and never in the file, so that a file written over months stays internally
    consistent.
20. As a site operator whose meter does not record a quantity, I want that column empty
    rather than absent, so that every meter's file has the same shape.
21. As a site operator, I want my existing Load Profile file closed and a new one opened
    when the columns change, so that no row is ever written under a header that does not
    describe it.
22. As a site operator, I want the closed file kept under a dated name beside the new one,
    so that months of history are not lost to a column change.
23. As a site operator who renames a site, I want the file to start a new edition, so that
    a file never claims a site name that was not in effect when its rows were written.
24. As a site operator, I want all three files in one folder governed by one switch, so
    that there is one thing to configure and one thing to point Syncthing at.
25. As a vendor signing a licence, I want the new files to be covered by the feature keys
    that already exist, so that a licence signed last month does not silently lack them.
26. As a developer, I want the eleven columns to cost no extra meter read, so that adding
    them cannot slow a fifteen-minute cycle or a shared serial line.
27. As a developer, I want a column whose scaler cannot be resolved to be empty rather
    than unscaled, so that a magnitude error can never masquerade as data.
28. As a developer, I want the acceptance of the eleven columns to require a real meter
    read, so that a column that resolves no scaler cannot pass a suite of fakes.
29. As a developer, I want a parity assertion that says v1 is blank where v2 must not be,
    so that nobody later "fixes" the correct implementation to match v1's mapping bug.
30. As a developer, I want one declaration per load-profile column carrying its unit, its
    scaler source and whether it is a passthrough, so that a new column is one line rather
    than a change to three parallel structures.
31. As a customer running a Database Destination, I want the new columns to reach my own
    database on the next cycle, so that the mirror stays a mirror.
32. As the owner, I want to be told plainly which columns will be empty on which meter
    model, so that the customer is not surprised by a blank column in a delivered file.

## Implementation Decisions

### The file contract, shared by all three files

- **A file header block of five lines precedes the column header row** in every one of
  the three files: customer, site name, meter serial, a literal `Setting : 1`, and the
  file-type label. Customer, site name and serial come from the device row, which already
  carries all three. `Setting : 1` is copied from the customer's samples verbatim; nobody
  on either side knows what it means, and the code must say so where it is written. The
  cost of copying it is one constant line; the cost of omitting it is a consumer that
  counts lines and reads every file wrong with no error.
- **When the file's own head — either the block or the column header row — does not match
  what the exporter would write today, the file is closed and a new one opened.** The old
  file is renamed with today's date appended before the extension; a name collision takes
  a numeric suffix. Every roll is logged. The check reads the file's first few lines, not
  the whole file.
- **This is an amendment to ADR 0013, not a new ADR.** ADR 0013 established that an
  appended file is a contract and a rendered view is not; this extends the same rule to
  say what happens when the contract itself changes. It meets all three ADR criteria on
  its own (hard to reverse, surprising to a later reader who finds dated files in the
  folder, a real trade-off against rewriting old files in place), but it belongs inside
  0013 because it is that decision's next step rather than a different one.
- **One output folder, one auto-save switch, one scheduler job for all three files.** The
  Export Format settings grow two filename templates, one per new file. The job walks
  every device once and writes each file inside its own error boundary, so a billing file
  that cannot be written does not stop that device's Load Profile file.
- **Every export path also exists as a Save-now action** on the page that owns it — Load
  Profile has one already, Billing and Energy Summary gain one. This is not symmetry for
  its own sake: it is the only way an installer can prove the output folder is correct
  without waiting for a cycle, which is exactly the failure issue 017 shipped to a
  customer.
- **Watermarks are columns on the device row, never a table** (ADR 0008), following the
  Load Profile CSV's existing watermark. Two new ones, one per new file.
- **No new feature keys.** The billing file rides `billing`, the Energy file rides
  `energy_summary`, the new columns ride `load_profile`. A new sellable key would be
  absent from every licence already signed with an explicit feature list, silently and
  permanently, because the effective feature set is the intersection of what the licence
  named with what exists.

### The billing CSV

- **Twenty-four columns always**, the customer's manual sample. Their other program offers
  an operator a choice of twenty or twenty-four; a setting that changes a column count is
  incompatible with a file that appends, because flipping it forces a roll and leaves the
  consumer with two shapes and nothing to distinguish them.
- **Closed periods only.** The Open Period's Bill Date advances on every read (ADR 0018),
  so including it would append the same period repeatedly under a moving date. The
  All-Meters View made the same exclusion for the same reason.
- **`Record No` is the row's ordinal among that device's closed periods ordered by Bill
  Date**, computed in the query. Not a line count: a line count needs the file read on
  every append and resets when the file rolls. Billing Readings are not subject to
  retention, so the ordinal is stable for the life of the device.
- **Rate A, B and C only.** The customer's contract has three tariffs. Measured: Rate D is
  `0.0` on every column of the customer's own meter and NULL on all thirty-nine stored
  rows across the four development meters. If a four-tariff site ever appears, the roll
  mechanism makes adding the columns then a safe change.
- **The `Record Status` column carries `closed`.** With the Open Period excluded it is
  constant, but constant and true beats blank and ambiguous, and it means something the
  day the exclusion is reconsidered. The reset reason the driver reads is used to classify
  open versus closed and is not stored, so there is no other status to report here.
- **This column is not the Load Profile file's column of the same name** and the ticket
  must say so: one is a per-period open/closed state, the other a thirteen-bit
  per-interval word from the meter.
- Every column the file needs already exists on the Billing Reading. **No schema change,
  no driver change** — this is a formatter and a file writer.

### The Energy Summary file

- **Both forms, one layout**: `Date` plus the eight Time-of-Use columns the screen shows,
  and **no total row** in either. A total row cannot exist in an appended file, and giving
  the on-demand file one would make two shapes to maintain for one concept. The total
  belongs to the screen.
- **ADR 0012 is untouched.** Nothing is stored, nothing is read back, and the summary is
  still derived on every request. A file is a snapshot somebody chose to take.
- **The daily file's watermark advances whether or not a row was written.** A day with no
  interval readings is simply absent, permanently. The alternative — holding the watermark
  until a day produces a row — makes a genuine data gap into a window the job re-queries
  forever with nothing to report it.
- **The consequence is stated, not hidden**: readings that arrive late, through the
  ninety-day load-profile backfill, never reach the daily file. Together with a holiday
  entered after the fact, that gives exactly two reasons the archive can be stale, and
  **the on-demand save is the single corrective for both**. That is one mechanism, not
  two.
- **Adding or editing a Holiday raises a notification naming how many meters' files
  already hold the affected day**, computed from the energy watermarks, and pointing at
  the on-demand save. Deleting a Holiday warns the same way. A holiday dated in the future
  raises nothing. The count is computed server-side and returned by the Holidays endpoint;
  the page never derives it.
- The notification is persistent, not a toast — it asks the operator to do something
  later.

### The eleven Load Profile columns

- **Column order follows the customer's sample**, which inserts the three phase angles
  before `Frequency (Hz)` rather than appending everything at the end. This moves an
  existing column's position, which is only survivable because of the roll rule above.
- **Column names follow v2's own convention**, continuing the 2026-08-11 ruling that
  corrected v1's four mis-united energy headers. The customer's spelling repeats the same
  error (`Import kVar Reactive`) and carries stray whitespace. Adopting it verbatim would
  leave one file using two naming conventions.
- **The interval status word is stored as the raw integer and decoded at render time**,
  both for the file and for the screen, through one shared helper. The bit meanings are
  settled for the CEWE word and unverified for the SMART TCC one; storing decoded text
  would make every historical row permanently un-decodable on the day the TCC word is
  finally verified. This is also what v1 does.
- **Its database column is named for the product term, not the file header.** The glossary
  already separates **Interval Status** (a per-interval word from the meter) from
  **Records** (a per-day completeness count), and the Billing Reading already owns a
  differently-meaning `record_status`. The file keeps the customer's header.
- **Multiple set bits join with a pipe, not a comma.** v1's comma-joined rendering never
  reached a CSV — it existed only on v1's screen — so no parity is broken, and a comma
  inside a cell survives only if every downstream consumer honours CSV quoting, which is
  untestable from here. Most rows carry a single word anyway.
- **The display unit setting reaches the four power columns on the screen and never in the
  file.** This is ADR 0013's own boundary; until now no column existed that the boundary
  ran through in both directions, so this is the first time the rule is testable rather
  than merely stated.

### The load-profile column declaration (a prefactor)

The map from `(OBIS, attribute)` to a stored field currently holds a three-part tuple and
the scaler resolution hardcodes a single COSEM class read at a single attribute. The
eleven columns need three things that shape cannot express:

- the average power columns are a **Demand Register**, a different COSEM class whose
  scaler sits at a different attribute;
- the interval status word has **no scaler at all** and must bypass multiplier resolution
  entirely, the way Demand Time cells already do;
- the export power columns resolve their scaler from a **different class than their import
  counterparts do**, so a scaler candidate is an address *and* a class, not an address.

The map's value therefore becomes a small frozen declaration carrying the field, the
expected unit, the ordered scaler candidates as address-and-class pairs, and a passthrough
flag — with defaults, so a later addition is one line. Scaler candidate resolution takes
those pairs rather than one class for all of them.

**This lands as its own ticket, first, changing no behaviour.** It is a mechanical rewrite
across four driver files that the type checker fully covers. Mixing it with the column
addition would make a diff in which nobody can tell which edit changed a value.

### What the probes measured (read-only, one association each, 2026-09-09)

Run against the development Prometer 100 `WP079074`. These numbers decided three of the
decisions above and are the reason the ticket can name a scaler source per column instead
of discovering it during implementation.

- **Every own-address scaler read was denied**, on all twelve targets. The sibling address
  is the only path on this meter family, which matches the 2026-08-09 billing scan.
- **Nine of the eleven resolve through the D=7 sibling**: the three phase angles as
  degrees, the three line-to-line voltages as volts, and the two import power columns as
  active and reactive power. Every scaler is `1.0`.
- **The two export power columns needed a different source.** Their D=7 siblings are
  denied; their maximum-demand siblings answer correctly, but only when read as an
  Extended Register rather than a plain one.
- **The interval status word offers no scaler**, confirming it must be a passthrough
  column.
- **Every scaler on this meter is `1.0`**, which is the most important measurement of the
  set: a scaler that fails to resolve does not produce a wrong magnitude, it produces
  nothing at all. **The failure mode of this whole ticket is a silently empty column, not
  a wrong number.**

### Borrowing a maximum-demand scaler for an average-power column

The two export power columns take their multiplier from the meter's maximum-demand export
registers: the same physical quantity and the same unit, a different statistic. The
billing path already borrows across addresses this way, and ADR 0002 requires the scaler to
be read rather than assumed, which this does.

Because every scaler on the reference meter is `1.0`, a wrong borrow would produce a
plausible number rather than a blank. **The acceptance criterion is therefore a
cross-quantity check** — average export power over an interval, multiplied by the interval
length, against the export energy stored for that same interval. That compares two numbers
that arrive by different routes; comparing a stored value against the register it came from
would prove only faithful transcription.

### Per-model coverage, from the scans

- **Prometer 100** — all eleven.
- **Premier 550** — the interval status word only.
- **Saral 305** — none.
- **SMART TCC** — the three phase angles, at a different address. Its status word is a
  different object whose bit meanings nobody has verified on hardware, and v1 deliberately
  refused to map it; it stays blank. The phase angles are mapped from the July scan and
  the ticket must record that the mapping is **not hardware-verified**, because the test
  meter does not answer on either port.

A model that does not record a quantity gets an empty column, which is the shipped and
accepted behaviour for `Frequency (Hz)` today.

### The defect this grill closed

`avg_geo_pf` is NULL on all eighty-seven thousand stored rows, including on the two meters
whose driver maps it and whose hardware records it. The cause is now measured rather than
suspected: the sibling register reports its unit as *no unit* (255) and the column map
declares *none* (0), so the multiplier is rejected and the column stores nothing, with no
error anywhere. The fix is one enumeration value.

**It gets its own ticket in this phase, after the prefactor and before the columns.** Not
folded into the prefactor, which declares itself behaviour-preserving and must stay true;
not folded into the column work, where a fix to a shipped defect would be invisible among
eleven additions. Its acceptance is the same real-meter read the eleven columns need.

### Consequences outside this phase

**The eleven columns reach the customer's own database automatically.** The Database
Destination derives its schema from our model and reconciles by adding missing columns, so
the next sync issues an add-column statement against the customer's MySQL. This is designed
behaviour with a precedent — the Billing Reading grew from forty to sixty columns the same
way — and ADR 0020 says a destination mirrors our window, so excluding the new columns
would make it a partial mirror with no rule saying which parts. It is still a schema change
fired into somebody else's database, and the ticket says so where a reader will find it.

## Testing Decisions

A good test here asserts what a person opening the file would see. Every rule in this spec
that matters to the customer is visible in the bytes on disk, so the bytes on disk are what
the tests read. None of them reaches inside the exporter to check how it got there.

**Four seams, all of them already in the suite. No new seam is introduced.**

1. **The device-level export, end to end.** Set the settings, put real rows in the
   database, run the export, read the produced file, assert its content. This one seam
   carries the header block, the column sets of all three files, the closed-period
   exclusion, `Record No`, the dash for absent and sentinel timestamps, four-decimal
   trimming, the watermark advancing over an empty day, and the roll — old file renamed,
   new file opened, no row under a header that does not describe it. Prior art: the
   existing Load Profile CSV export tests, which already have exactly this shape.
2. **The pure formatter.** No I/O, no database. The many small cell-level rules live here
   because they are cheap to state and unambiguous to check: trailing-zero trimming, the
   pre-2001 sentinel, date-token translation, the three header tuples, and the pipe-joined
   status decode. Prior art: the existing export-format tests.
3. **The driver's load-profile read.** Given a buffer carrying the full capture list, the
   eleven fields land in the right places; scaler candidates are tried in declared order;
   and **a column whose scaler resolves to nothing stores nothing rather than a raw
   count**. Prior art: the existing SMW110 load-profile tests, plus the driver-contract
   test that holds the invariant across every registered model.
4. **The API.** The three Save-now actions, and the count the Holidays endpoint returns for
   the stale-file warning — computed on the server and returned finished, because the page
   cannot see the watermarks and an exporter cannot call TypeScript. Prior art: the
   existing Holidays and Load Profile export endpoint tests.

**The file-roll helper is deliberately not tested directly.** It is exercised through seam
1, by its outcome. A direct test would pin the tests to a function shape that is still
moving, instead of to the behaviour an operator sees.

**Two things are deliberately not automated.**

- **The web pages** have no test runner, by design. Their gate is lint plus a build that
  fails on type errors, as it is for every page in this product.
- **The real-meter read cannot be automated at all here.** The meter fake is applied to
  every test automatically, so it answers with whatever the fake declares regardless of
  whether a scaler would resolve against real hardware. This is precisely the failure that
  let `avg_geo_pf` ship empty through every gate for eighty-seven thousand rows. The eleven
  columns and the `avg_geo_pf` fix therefore carry a **hand-run acceptance criterion**:
  read a real Prometer 100, confirm every column is non-NULL, and attach the numbers to
  the ticket. A probe script exists for it and belongs in the repository's script directory
  with its output recorded under the meter notes, where evidence read off hardware lives.

**The parity criterion is written to reject the wrong fix.** Parity against v1 is asserted
over the fourteen existing columns. For the phase angles it is inverted: v1's map reads the
wrong D value on this meter family and leaves the columns NULL, so the test asserts that v2
is **not** NULL there, with the reason in the test's name. Without that, the correct
implementation looks like a regression and the obvious repair is to break it.

The full suite in parallel is the gate for every ticket, not a subset of it.

## Out of Scope

- **The central-server push.** Still SPEC §3.8 and unbuilt; a separate transport with a
  separate contract.
- **Storing the Energy Summary in the database.** ADR 0012 forbids it, and the reason it
  forbids it is the reason the file exists.
- **Real-time notification of an unattended capture or export.** Decided against in the
  previous phase; the same reasoning holds — it fires into an empty room.
- **A licence registry.** Still absent, still deliberately out of scope.
- **Decoding the SMART TCC status word.** Needs the meter reachable and its bits verified
  against a known state.
- **The fourth Prometer 100 phase-angle object.** Captured, mapped to nothing, recorded so
  it is not rediscovered.
- **Special Days import and the four un-driven models.** Phase 4; the latter needs its own
  ADR because the model catalogue is a locked artefact.
- **Making the export folder or its settings per-meter.** Machine-wide by an earlier
  decision that nothing here challenges.
- **Any change to the capture files.** Their filename shape is a decision, not a bug.

## Further Notes

**Tell the customer, do not ask them.** Five things will differ from their samples and none
of them is a question: the column headers use our corrected unit names; there is no Rate D;
the status column carries words rather than dots; the line-to-line and power columns hold
values on the Prometer 100 only, and a SMART TCC gets phase angles but a blank status
column until that meter is reachable; and on their own machine the billing file will be
empty until the first period closes, because the single reading stored there today is a
provisional one.

**The eleven columns cost nothing at the meter.** Every one of them is already inside a
buffer the product reads every cycle and discards for want of a field. On one model this
has been measured: twenty-six thousand rows per device were being written to keep two
useful values out of thirteen.

**One number to watch during implementation.** The reference meter reports `1.0` for every
scaler, so a scaler bug will not look like a bug. It will look like a meter with no data —
which is what the defect this grill closed looked like for eighty-seven thousand rows.

**Glossary work is two edited sentences, not a new term.** The Interval Status entry gains
its separator; the Export Format entry stops describing one file and starts describing
three. Both land with the code that makes them true.
