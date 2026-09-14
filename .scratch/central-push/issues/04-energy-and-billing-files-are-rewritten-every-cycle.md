# 04: The Energy and Billing files are rewritten whole every cycle

**What to build:** The Energy Export File always matches the Energy Summary page, because every
export cycle rewrites it from the stored rows for the last 90 days. The Billing Export File is
rewritten every cycle too, and holds every closed period the program has, because the program
never discards billing. Neither file can be stale by more than one cycle, so both per-device
"exported through" watermarks disappear. **Save to file** keeps saving a chosen range into a file
of its own. Decision records: ADR 0022, ADR 0023; spec: `.scratch/central-push/spec.md`.

**Blocked by:** 01 (the stored Energy Summary), 02 (atomic whole-file rewrite)

**Status:** ready-for-agent

- [ ] Each export cycle rewrites the Energy Export File whole, from `energy_summary_days` for the
      last 90 days, keeping its 9-column layout and header block
- [ ] Each export cycle rewrites the Billing Export File whole, with every closed period, keeping
      its 24 columns, `Record No` ordinal and header block, with the Open Period still excluded
- [ ] **Matches the page**: after a Holiday change and one recompute, the Energy file's rows equal
      the stored rows for the same days
- [ ] **All closed periods**: a closed period older than 90 days is still in the Billing file
- [ ] **Window**: the Energy file carries no day older than 90 days
- [ ] A migration drops `devices.energy_exported_through` and `devices.billing_exported_through`,
      and nothing in the application reads or writes them
- [ ] **Save to file** writes the chosen range from `energy_summary_days` into its own range-named
      file, as today
- [ ] The auto-save switch still governs both files: off writes nothing
- [ ] Every test above is mutation-probed: reverting the behaviour it names turns it red
- [ ] `CLAUDE.md`'s digests for ADR 0022 and ADR 0023 record what landed
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `pytest -n auto` in `app/`
- [ ] No real-meter read is required: no driver changes
