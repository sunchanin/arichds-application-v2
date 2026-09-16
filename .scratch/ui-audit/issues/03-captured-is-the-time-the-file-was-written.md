# 03: "Captured" is the time the capture file was written

**What to build:** On the Billing All-Meters View, the **Captured** column shows when the
Capture for that bill was actually written to the capture folder, and is blank when no file
exists for it; the toast after a manual Capture image names that same time. The customer
asked for this twice — *"เวลา capture จะเดขึ้นเวลาดึงแบบ manual และ auto"* and *"แต่แสดงเวลา
cap"* (W1 › Billing อันเก่า › AF14, Bill ใหม่ › F60). Today the column echoes the bill's
`read_at` whenever capture is switched on: on the dev machine it shows `2026-09-01 19:02`
for a period that has no capture file on disk at all.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] A billing period gains a nullable `captured_at` (UTC) written by the capture service
      at the moment it finishes writing that period's document(s) — on the automatic path
      when a new closed period is captured, and on the manual path when Capture image is
      pressed (the anchor period, ADR 0015). Migration adds the column; existing rows stay
      `NULL` (no backfill from file timestamps).
- [ ] The All-Meters View's `captured_at` is that column and nothing else. Test: a period
      that was read but never captured shows `captured_at = None` even with a capture
      folder configured. Mutation probe: falling back to `read_at` turns it red.
- [ ] A capture that fails to write leaves `captured_at` unchanged. Test with the write
      hardening's existing failure path.
- [ ] After a manual Capture image the toast reads "Captured <local time>" and the
      All-Meters row shows the same instant (local, like the rest of the page).
- [ ] The ADR 0015 filename stem and the capture folder layout are untouched.
- [ ] `antd-ui` skill invoked for the web change; `fastapi` for the API change.
- [ ] Gate: `ruff format --check .` + `ruff check .` + `pytest -n auto` green in `app/`;
      `pnpm lint` + `pnpm build` green in `web/`.
