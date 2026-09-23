# 03: The Billing Export File lives in the meter's subfolder, beside its captures

**What to build:** A meter's billing file is written to `<Billing Folder>\<Meter Serial>\<name
from the billing filename template>` — the same subfolder its PDF/xlsx/PNG captures already use
(the serial token sanitised the same way) — by the 15-minute rewrite and by *Save billing file
now* alike, creating the subfolder when it is missing. The file 0.8.2/0.8.3 left at the folder's
top level is never deleted or moved (the owner removes it by hand). The File Upload Destination
finds the billing file inside each device's subfolder and sends it once, as `export/<name>` in the
Upload Manifest exactly as today; the capture walk never sends it a second time as
`captures/<serial>/<name>`, never sends the writer's temp file, and a stale top-level billing file
is not sent at all. The Load Profile CSV and the Energy Export File stay flat in their own folders.

**Blocked by:** 02 (each export file only in its own folder) — same writer, same cycle, same test
file

**Status:** ready-for-agent

- [ ] The billing writer's target is the meter's subfolder of the Billing Folder; a device with no
      Meter Serial still holds quietly; the subfolder is created on first write
- [ ] Tests: `export_device_billing` lands at `<folder>/<serial>/<name>` and a pre-existing
      top-level file with the same name keeps its bytes; *Save billing file now*'s response path
      is inside the subfolder
- [ ] Upload cycle tests against the in-memory transport: with a billing file in the subfolder, a
      stale copy at the top level, the writer's temp file beside it and a capture in the same
      subfolder, the puts are exactly `export/<name>` (the subfolder's bytes) and
      `captures/<serial>/<capture>` — mutation checks: listing the top level instead of the
      subfolder sends the stale bytes; dropping the template exclusion from the capture walk
      sends the billing file twice
- [ ] ADR 0015 gains an amendment (the billing file shares the meter's capture subfolder), the
      Billing page's help text names the subfolder, CLAUDE.md's 0015/0023 digests follow
- [ ] Gate: `ruff format --check`, `ruff check`, `pytest -n auto` (app), `pnpm lint && pnpm build`
      (web)
