# 05: Avg Geo PF resolves a scaler on the Prometer 100

**What to build:** The Load Profile's **Avg Geo PF** column carries a value on the
Prometer 100, or is declared unsupported for that model and shown as "—" without a warning
on every cycle. Today the driver logs *"could not resolve a scaler for 1.0.13.24.0.255
(avg_geo_pf) — avg_geo_pf stays unscaled (None) on every row"* on every load-profile walk of
both Prometer 100 units, and the column is empty in the file and on the page. This is the
sibling of `docs/issues/018` (export_active_kw), which resolves its scaler through a borrowed
register because the meter serves none at the column's own address.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] The read-only probe reads attribute 3 (`scaler_unit`) of `1.0.13.24.0.255` and any
      candidate sibling register on `WP079074` and `WP080652`, and the result is recorded in
      `docs/meter-notes/lp-new-columns-scan.md` with the date. `gurux-dlms` skill invoked
      first.
- [ ] If a scaler is obtainable (own address or a borrowed sibling, as `export_active_kw`
      does): the driver declares it, and a scoped read against the real meter fills Avg Geo
      PF with a plausible power factor (−1..1). The probe script derives its target from the
      column map, as the existing probes do.
- [ ] If no scaler exists on this model: the column is declared unsupported for the
      Prometer 100 so the page and the file show "—" for it consistently, and the warning
      fires **once per process per model**, not per cycle. Test: two walks emit one
      warning. Mutation probe: warning on every walk turns it red.
- [ ] Issue 018's note is updated to say the pair was resolved together (or why not).
- [ ] Gate: `ruff format --check .` + `ruff check .` + `pytest -n auto` green in `app/`;
      probe output pasted into the ledger.
