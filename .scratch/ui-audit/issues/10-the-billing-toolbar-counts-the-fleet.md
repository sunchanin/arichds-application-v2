# 10: The Billing toolbar counts the fleet

**What to build:** The Billing page carries the strip the customer pointed at in the v1
screenshot (*"อยากได้แบบเก่านะ"* — W1 › Bill ใหม่ › F60): **Total Devices · Devices with
Issues · Complete**, an **Auto** indicator, and the selected device's **Site Name / Site
Code**. In v1 those three counters were hard-coded `0` and the "● Running / Stop" control was
a mock that was later commented out (v1 `Billing/index.tsx:742-773`, ADR 0017 there) — so v2
gives them real definitions taken from what the All-Meters View already computes (M11,
§7.3), rather than copying numbers that never meant anything.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] **Total Devices** = every device on the machine; **Devices with Issues** = devices whose
      All-Meters status is `paused`, `not_answering`, `never_billed` or `behind`;
      **Complete** = devices whose status is `ok`. The three always sum to Total. Test: a
      fleet with one `not_answering` and one `behind` counts 2 issues. Mutation probe:
      counting only `not_answering` turns it red.
- [ ] The counters come from the same query the All-Meters View uses — no second definition
      of "issue"; the strip and the tab can never disagree.
- [ ] **Auto** reads "Every 15 min · last cycle HH:MM" (local) from the scheduler's last
      billing change-check, or "Not yet run since start" — an indicator, **not** a Stop
      button: the scheduler holds no persisted state to stop (ADR 0008), and pausing is a
      per-device action that already exists on the Devices page.
- [ ] **Site Name** and **Site Code** appear beside the device select when one device is
      chosen (both are device fields today); "—" when the field is empty; hidden on "All
      devices".
- [ ] The strip is hidden in capture mode, like the other operator controls (D13), so the
      `.png` stays the table the customer's screenshot shows.
- [ ] English-only, AntD tokens, `antd-ui` skill invoked; render test asserts the three
      numbers and the Auto text.
- [ ] Gate: `pnpm lint` + `pnpm build` green in `web/`; `ruff format --check .` +
      `ruff check .` + `pytest -n auto` green in `app/`.
