# `export_active_kw`'s multiplier is unverified against a non-zero value

**Type**: AFK-blocked · **Found**: M13 issue 06 hardware gate, 2026-09-09 · **Blocks**: nothing
shipped; it decides whether one shipped column can be trusted

## The problem

`export_active_kw` is one of the four power columns M13 added. It resolves its scaler through a
**borrowed sibling** — the `D=6` maximum-demand register read as an `ExtendedRegister`
(`1.0.2.6.0.255`) — because the meter serves no scaler at the column's own address. That route
is a declaration, and the only way to prove a declaration is to compare the value it produces
against the same quantity arriving by a different route.

That comparison has been run and it **could not answer**:

```
scripts/probe_lp_column_fill.py --host 203.170.151.152 --hours 3
  export_active_kw       12 row(s) but every one is zero on both sides — VACUOUS, proves nothing
  export_reactive_kvar   12/12 row(s) non-zero, worst error 0.00 %  OK
```

The reference site does not export active power. Zero times an interval equals zero, so a
wrongly borrowed scaler reports exactly what a correct one reports.

## What is and is not known

- **The scaler resolves.** The read does not fail, and the column is not NULL — it is `0.0`.
- **The route is proven on its twin.** `export_reactive_kvar` takes the identical route through
  the identical COSEM class and was verified 12/12 rows at 0.00 % error. That narrows the risk
  to "the same mechanism, a different register".
- **The multiplier itself is unproven.** `export_reactive_kvar`'s scaler and
  `export_active_kw`'s are two separately stored values on the meter. Verifying the *mechanism*
  is not verifying the *number*, and on this meter family every scaler happens to be `1.0` —
  which is exactly the condition under which a wrong scaler is invisible.
- **The failure mode if it is wrong** is a plausible number rather than a blank, on a column a
  customer reads. It is not a crash and no test can catch it.

## Why this is an issue and not a documentation bullet

`docs/REMAKE-PLAN.md` §7.7 and `docs/meter-notes/lp-new-columns-scan.md` both record this
accurately. Neither enforces anything. The precedent is the Mitsubishi fixed-password defect,
written up perfectly in `docs/meter-notes/smw110w4-scan.md` and left unfixed for weeks because
a prose record has no owner and no closing condition (`docs/issues/002:4-7` cites the same
lesson). This file exists to give the gap a closing condition.

## Acceptance criteria

- [ ] Run `scripts/probe_lp_column_fill.py` against a site that **exports active power**, so the
      cross-quantity check reports a non-zero comparison count for `export_active_kw`
- [ ] The reported worst error is within the probe's 5 % band, on at least 3 non-zero rows
- [ ] The result is appended to `docs/meter-notes/lp-new-columns-scan.md` with the date, host and
      row count — a pass and a failure are equally worth recording
- [ ] If it **fails**: the sibling declaration in `prometer100.py`'s
      `LOAD_PROFILE_COLUMN_MAP` is corrected, and a replay test pins the corrected scaler so the
      next reader cannot un-learn it
- [ ] `pytest -n auto` from `app/` stays green either way

## Blocked by

**A reachable meter that exports active power.** No test meter we have does — the four in
`CLAUDE.md` -> "v1 as reference" are all import-only sites. This cannot be closed from a desk,
and it must not be closed by inference from `export_reactive_kvar`: the two carry separate
scalers.

Do not "fix" this by reading the column's own address for a scaler. It has none — that is the
whole reason a sibling is borrowed (ADR 0002, and `docs/meter-notes/lp-new-columns-scan.md`).

## Note 2026-09-16 — the `avg_geo_pf` pair was re-checked and holds (ui-audit ticket 05)

`avg_geo_pf` borrows its scaler the same way this column does (a declared sibling, ADR 0002),
and the dev machine's log suggested it had stopped resolving. It had not: the 960 warnings
were all from build 0.5.0, before M13 issue 05's `NO_UNIT` correction; the re-probe on
2026-09-16 resolves the sibling on **both** Prometer 100 units and the column fills 18/18
Logger-1 rows on each (`docs/meter-notes/lp-new-columns-scan.md` §4). That closes the sibling
question, not this one: `export_active_kw` still needs a site that exports, exactly as the
acceptance criteria above say.

