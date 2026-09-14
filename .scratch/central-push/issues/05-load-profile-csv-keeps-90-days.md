# 05: The Load Profile CSV keeps 90 days

**What to build:** The Load Profile CSV stops growing. It keeps receiving new rows every cycle
exactly as it does today, and once a day it is rewritten to hold only the last 90 days, so it
never carries more than 91. A customer with limited disk space, and anyone mirroring the folder
with Syncthing, sees one bounded file per meter. Decision record: ADR 0023; spec:
`.scratch/central-push/spec.md`.

**Blocked by:** 02 (atomic whole-file rewrite, and the Load Profile CSV rendering its window)

**Status:** ready-for-agent

- [ ] A daily job — at the retention job's cadence, registered after it — rewrites each device's
      Load Profile CSV to the 90-day window using ticket 02's rewrite
- [ ] **Window**: after the daily rewrite, the file holds no row older than `RETENTION_DAYS`
- [ ] **Cadence**: the fifteen-minute export cycles only ever append to the file; they never
      rewrite it
- [ ] **Faithful**: a file rewritten by the daily job equals, for the days it keeps, the file that
      appending alone had produced
- [ ] **Watermark**: the first append after a rewrite adds only rows newer than the newest row
      written, with no duplicate and no gap
- [ ] The auto-save switch still governs the file: off, the daily job writes nothing
- [ ] Every test above is mutation-probed: reverting the behaviour it names turns it red
- [ ] `CLAUDE.md`'s digest for ADR 0023 records that the Load Profile CSV now keeps 90 days
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `pytest -n auto` in `app/`
- [ ] No real-meter read is required: no driver changes

**Why a daily job rather than "trim when the oldest row falls outside the window"** (the spec's
wording): finding the oldest row means parsing the file's timestamps, and their format is the
operator's own Export Format setting. A daily job gives the same file — at most 91 days, rewritten
at most once a day — without reading the format back. A restart may run it once more that day,
which rewrites an identical file.
