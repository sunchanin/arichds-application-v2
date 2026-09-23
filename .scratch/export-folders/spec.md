# Spec — Each export file has its own folder

**Status:** ready-for-agent · customer request relayed by the owner 2026-09-23 · reverses the
M13 rule "one folder, one switch, one date format for every export file" (SPEC §3.6 note, ADR
0023's "the export folder") for the *folder* only — the switch and the date format stay shared.
Tracker: local (`.scratch/export-folders/issues/` once `/to-tickets` runs); no GitHub issue.
Glossary: CONTEXT.md → *Load Profile CSV*, *Billing Export File*, *Energy Export File*,
*File Upload Destination*, *Upload Manifest*. **Owner instruction (2026-09-23): the folder for
each file is set on that file's own page — not gathered on the Export Format page.**

## Problem Statement

The customer keeps the three export files in three places: the billing file goes to the people
who reconcile bills, the Load Profile CSV to the people who watch consumption, the Energy file
to a third. ARICHDS writes all three into one folder, chosen on the Load Profile page, so the
customer has to sort them by hand — and an operator pressing **Save billing file now** on the
Billing page is told to configure a folder on a page about a different file.

## Solution

Every export file gets its own folder, set on the page that owns the file: the Load Profile
page keeps its **Output folder** (the Load Profile CSV, as today), the Billing page gains
**Billing file folder** beside the Capture folder, and the Energy Summary page gains **Energy
file folder** beside *Save to file*. A folder left empty means "use the Load Profile CSV's
folder", so an installation that set one folder before this change keeps writing exactly where
it did until someone chooses otherwise. The scheduler's rewrite, the two *Save … now* buttons
and the File Upload Destination all read the folder of the file they handle. The Export Format
page keeps the templates and the date format and says where each folder is set.

## User Stories

1. As an admin, I want a **Billing file folder** on the Billing page, so that the billing file
   is configured where I press *Save billing file now*.
2. As an admin, I want an **Energy file folder** on the Energy Summary page, so that the Energy
   file is configured where I press *Save to file*.
3. As an admin, I want the Load Profile page's **Output folder** to keep its meaning — the Load
   Profile CSV's folder — so that nothing I set before this change moves.
4. As an admin, I want an empty Billing or Energy folder to mean "the Load Profile CSV's
   folder", so that upgrading changes nobody's files until I choose to.
5. As an admin, I want each folder validated the way the Output folder is (absolute, inside the
   allowed roots, existing), so that a typo is refused with a sentence I can act on.
6. As an admin, I want to save the Billing file folder with the same Save button as the Capture
   folder and the Capture image style, so that the Billing page has one place for its folders.
7. As a `user`, I want to see each folder and not be able to change it, so that the read/change
   split matches every other setting.
8. As an operator, I want *Save billing file now* to write into the Billing file folder — or the
   Load Profile CSV's folder when it is empty — so that the toast names the folder I chose.
9. As an operator, I want *Save billing file now* with neither folder set to refuse with a
   sentence naming **Billing file folder on this page**, so that I am not sent to another page.
10. As an operator, I want *Save to file* on the Energy Summary page to behave the same way with
    the Energy file folder, so that the two buttons follow one rule.
11. As an operator, I want *Save CSV now* to keep writing into the Output folder, unchanged.
12. As an operator, I want the 15-minute rewrite of the billing file and the Energy file to use
    their own folders, so that a hand-pressed save and the scheduler never disagree.
13. As an operator, I want the Auto-save switch to stay one switch for all three files, so that
    one control still says whether files are written at all.
14. As an operator, I want the date format and the three filename templates to stay on the
    Export Format page, unchanged, so that only the *where* moved.
15. As an operator, I want the Export Format page to tell me on which page each folder is set,
    so that the page that governs every file still points at all three.
16. As the customer, I want the File Upload Destination (FTP) to send the billing file from the
    Billing file folder and the Energy file from the Energy file folder, so that a file I moved
    does not stop reaching the server.
17. As the customer, I want the Upload Manifest's keys (`export/<name>`) unchanged, so that the
    server side sees the same paths as before.
18. As the customer, I want a billing file still sitting in the old shared folder after I moved
    the setting to be **not** re-sent as the billing file, so that the server gets one file per
    name, from its own folder.
19. As the customer, I want two files to be allowed the same folder, so that keeping the Load
    Profile CSV and the Energy file together is still possible.
20. As the customer, I want no change to the Database Destination or the Central Push, since
    neither reads a folder.
21. As a developer, I want the folder of each file resolved in one place (the settings module),
    so that the writer, the endpoint and the upload cycle cannot disagree on the fallback.
22. As a developer, I want no migration, so that the change is three new setting rows at most.
23. As the owner, I want SPEC §3.6, ADR 0023 and the CLAUDE.md digest to record that the "one
    folder" rule is gone, so that the next reader does not "restore" it.

## Implementation Decisions

**Settings.**
- Two new machine-wide keys, `export_billing_output_dir` and `export_energy_output_dir`, default
  `""`, stored through the existing settings table; no migration. `export_output_dir` keeps its
  key and its meaning (the Load Profile CSV's folder) — renaming it would touch every existing
  install for nothing.
- Three readers in the settings module, the only place the fallback lives: the Load Profile
  folder (as stored), the billing folder (its own value, else the Load Profile folder), the
  Energy folder (its own value, else the Load Profile folder). Every writer, endpoint and the
  upload cycle call these; none reads the raw keys.

**API — each folder on its own endpoint, the one its page already calls.**
- `GET`/`PUT /api/billing/settings` gains `export_billing_output_dir` beside `capture_dir` and
  `capture_style`; omitted on `PUT` keeps the stored value (the same rule `capture_style`
  follows). Validated with the same directory validator and allowlist `export_output_dir` uses,
  named in its own 422. Admin-only write, any authenticated read.
- A new pair `GET`/`PUT /api/energy/settings` carrying `export_energy_output_dir` — the Energy
  Summary page has no settings endpoint today; it gets the smallest one, the same shape as the
  billing pair, gated by the `energy_summary` feature the page already carries.
- `GET`/`PUT /api/settings/export-format` is unchanged in shape: it does not carry the two new
  folders, because the Export Format page does not show them (owner instruction).
- The two *Save … now* 422s name the folder field on the same page, never another page; the
  Load Profile one is unchanged.

**Writers and the scheduler.**
- The billing file writer and the Energy file writer read their own folder through the
  settings readers; the Load Profile CSV writer is untouched. An empty resolved folder still
  holds quietly on the scheduler path and is a 422 on the button path, as today.

**File Upload Destination.**
- The cycle reads the three resolved folders and lists each (folder, template) pair — the Load
  Profile folder against the CSV template, the billing folder against the billing template, the
  Energy folder against the Energy template — instead of one folder against three templates.
  Relative paths in the Upload Manifest stay `export/<name>`. A folder shared by two files is
  listed once. The per-device candidate order (CSV, billing, Energy) is unchanged.

**Web.**
- Billing page: the Capture folder card becomes the page's folder card — Capture folder,
  Billing file folder (extra text: "Leave empty to use the Load Profile page's Output folder"),
  Capture image style, one Save.
- Energy Summary page: a small admin card with the Energy file folder and its Save, beside the
  *Save to file* control; read-only for a `user`.
- Load Profile page: unchanged apart from the Output folder's help text, which now says the
  billing and Energy files use it too unless their own folders are set.
- Export Format page: the intro text names the three pages; the billing template's help text no
  longer claims both files share a folder.

**Documents.** SPEC §3.6's "one folder" note and §3.5's folder sentence amended; ADR 0023
amended in place ("the export folder" → "each file's folder"); CLAUDE.md digest one clause.

## Testing Decisions

A good test seeds **two distinct folders** and asserts which one the file landed in, so a reader
that forgot the fallback, or read the wrong key, moves a path — never a test that passes with
one folder. Seams, highest first:

- **The two settings endpoints** (TestClient, `test_api_billing_settings.py` shape): default
  empty; admin round-trips a folder; relative path is 422 and nothing is saved; omitted keeps the
  stored value; a `user` reads and is refused on write.
- **The two writers** (`test_billing_csv_export.py` / `test_energy_csv_export.py` shape, calling
  the writer directly): the file lands in its own folder and not in the Load Profile one; an
  empty own folder falls back; the Load Profile folder empty with the own folder set still
  writes.
- **The two buttons** (TestClient): 200 with the path under the own folder when only it is set;
  422 naming the field on the same page when neither is set.
- **The upload cycle** (`test_fileupload_cycle.py`'s in-memory transport): three folders, three
  files, one export group with unchanged manifest keys; a stale billing file left in the Load
  Profile folder is not sent; an empty billing folder sends the billing file from the Load
  Profile folder.
- Web: `pnpm lint && pnpm build`.
- Gate: `ruff format --check` + `ruff check` + `pytest -n auto` (app); the opt-in MySQL suite is
  not affected.

## Out of Scope

- A per-file Auto-save switch or a per-file date format.
- A folder for the capture documents other than the existing Capture folder.
- Moving files already written from the old shared folder to the new ones.
- Any change to the Database Destination or the Central Push.
- Gathering the folders on the Export Format page (explicitly ruled out by the owner).

## Further Notes

- A draft test file from before the owner's page-placement instruction exists at
  `app/tests/test_export_folders_per_file.py`; it targets the Export Format endpoint for the
  settings round trip and must be rewritten to the two page endpoints above before it is kept.
- The customer's machine (site TC) has `export_output_dir` set and both new keys absent, so the
  fallback is what keeps its files flowing on the day of the upgrade.
