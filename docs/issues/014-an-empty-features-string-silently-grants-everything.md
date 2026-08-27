# `sign --features ""` silently issues the most permissive licence there is

**Type**: AFK · **Found**: independently by both the implementer and the reviewer of issue 013,
2026-08-26 · **Blocks**: nothing · **Introduced**: `77ccf8a` (issue 010)

## The problem

`tools/arichds_vendor.py`'s `cmd_sign` reads:

```python
features = args.features.split(",") if args.features else None
```

`""` is falsy, so `--features ""` produces `features: None` in the signed payload. And
`licensing/features.py:47` reads:

```python
ceiling = SELLABLE_FEATURE_KEYS if license_features is None else frozenset(license_features)
```

**`None` means every sellable key.** So a vendor who types `--features ""` — believing they are
selling nothing, or clearing a value, or passing an empty variable from a script — issues the
**most permissive licence the product can produce**, silently, with exit 0 and no warning.

`None` and `[]` are deliberate opposites everywhere else in this system. Issue 012's whole
`enabled_features` design turns on keeping them distinct, and its D8 says so in as many words.
This is the one place the distinction collapses, and it collapses toward *more* access.

## Why it is worth an issue rather than a comment

Both agents on issue 013 found it independently, and both correctly refused to fix it — it was
outside their scope, even after the reviewer widened that scope for something else. It would
otherwise have survived as two sentences in `.claude/run-logs/issue-013.md`, which nothing reads
before signing a licence.

Note where it came from: **issue 010** added the validation that made this file trustworthy, and
this line is the one branch that validation does not reach, because `""` short-circuits before
any name is examined. A hardening pass left one door unlocked precisely because the door has no
name behind it to check.

## The shape of the harm

An empty string reaches this flag by accident far more easily than a wrong key name does:

- a shell variable that expanded to nothing — `--features "$KEYS"` with `KEYS` unset
- a script clearing a field it means to leave off
- a person typing `--features ""` to mean "none"

Every one of those intends *less* and gets *everything*. And the resulting licence is
indistinguishable at a glance from a deliberate grandfather-everything licence, because it **is**
one.

## What to do

Decide what `--features ""` means and make it say so. Three defensible answers — pick one and
write down why:

1. **Refuse it.** `""` is not a list; ask the vendor to say what they mean. Consistent with issue
   010's own decision that an entry empty after stripping is refused rather than dropped, on the
   grounds that "this tool does not guess" — and this is a larger guess than that one.
2. **Treat it as `[]`** — sold nothing. Consistent with `features.py:47`'s reading of an empty
   list, and the least surprising interpretation of an empty string.
3. **Keep it as `None` but warn**, the way issue 013 made a reserved key warn. Weakest of the
   three: it leaves the trap and adds a message.

Whatever is chosen, the *omitted* flag must keep meaning `None` — grandfather everything is the
correct and intended behaviour there, and issue 010's `TestGrandfatheringPathIsUntouched` pins it.
This issue is only about the empty **string**.

## Acceptance criteria

- [ ] `--features ""` has a decided meaning, implemented, and stated in the `--features` help text
      and the module docstring
- [ ] A test pins it, and a mutation that reverts it to `None` turns that test red
- [ ] `--features` **omitted** still yields `features: None` — the existing grandfathering test is
      unchanged and still passes
- [ ] `--features "   "` (whitespace only) resolves the same way as `""`, whichever way that is
- [ ] The decision is recorded where a reader of `features.py:47` will meet it, since that line is
      what makes the two spellings mean opposite things
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `python -m pytest -n auto` in `app/`
      (use `python -m pytest`; the console script under-collects — `docs/issues/004`)
- [ ] **Output Parity vs v1** is not applicable — v1 had no feature entitlement

## Blocked by

Nothing.

## Added 2026-08-27 — a sibling flag already decided this

Issue 015 shipped `--models` / `--brands` on the same `sign` command, and had to answer the same
question. It picked **hard error**: both flags are gated on the flag being *present*
(`is not None`), not on the string being truthy, so `--models ""` and `--brands ""` refuse the run
before anything is signed. 015's Out-of-scope forbade touching the `--features` branch, so the two
flags on one command now disagree — deliberately, and only until this issue lands.

That is not a ruling on this issue: `--features ""` may still resolve differently if there is a
reason. But if it does, the `sign` command will hold two spellings of an empty list that mean
opposite things, and that needs saying out loud rather than discovering. `_resolve_models` in
`tools/arichds_vendor.py` is the worked example either way.
