# 09: The latest bill row is highlighted, on the page and in the capture

**What to build:** On the Billing **History** tab, the newest closed period's row is tinted
lavender — and because the capture image is a screenshot of that very page (ADR 0017), the
same row is tinted in every `.png` the machine writes. This is the customer's ask, twice:
*"ถ้า capture ของรายตัวให้มี ไฮไลน์ แบบนี้ในบิลล่าสุดด้วย"* and *"สีที่ไฮไลต์ให้ตรงกัน กับรูปที่
cap"* (W1 › Billing อันเก่า › AF20, AF26). It is also exactly what v1 ships today: rows sorted
newest-first, the first row of page one carries `background-color: #f3e8ff` on its cells, on the
history table only (v1 `Billing/index.tsx` ~588–652). The M11 Status chip on the All-Meters View
stays as it is — that view shows one latest bill per meter, so tinting "the latest" there would
tint every row and say nothing.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] On History, the row for the **newest closed period in the current result** is tinted
      `#f3e8ff` (the exact v1 colour, so the customer's screenshot and ours match); every other
      row is untinted. Applies with one device selected and with "All devices" (then it is the
      single newest closed period across devices, as v1's #49 decided — one row, not one per
      device).
- [ ] The rule is by **bill date**, not by row index — a page that is sorted otherwise, or a
      date filter that removes the newest period, still tints the newest period *shown* and
      nothing when the table is empty. Test: with rows sorted oldest-first the tinted row is
      still the newest date. Mutation probe: "first row of page one" turns it red.
- [ ] Open Periods are never tinted: the Current tab has no highlight (v1 had none there
      either, and an Open Period's bill date moves on every read — CONTEXT.md).
- [ ] In capture mode the same rule runs on the ten periods the capture request seeded, so
      the anchor (newest closed) row is tinted in the `.png`. Verified by pressing Capture
      image on the dev machine and opening the file.
- [ ] The tint is a row class over AntD tokens, readable in the compact light theme and in
      the printed capture; no Thai strings; `antd-ui` skill invoked.
- [ ] The Status chip colours from ticket 07 and this tint do not fight: the tint is a
      background on History, the chip lives on All Meters — a test renders both pages and
      asserts the class appears only on History.
- [ ] Gate: `pnpm lint` + `pnpm build` green in `web/`; `ruff format --check .` +
      `ruff check .` + `pytest -n auto` green in `app/`.
