# Reserve a sellable key for the File Upload Destination, before the first licence is issued

**Type**: AFK · **Requested**: owner, 2026-08-26 · **Blocks**: nothing · **Blocked by**: issue 012
must be committed first (see the bottom)

## What is being asked

Add `file_upload_destination` to `SELLABLE_FEATURE_KEYS` (`app/src/arichds/constants.py`), taking
the count from ten to eleven sellable keys. **Reserve the key. Do not build the feature and do not
start selling it.**

## Why now rather than when the feature ships

The constant's own comment already argues this case, and this issue is that argument being applied
a second time:

> No licence has been issued yet (`SPEC.md:1050-1053`), so this key set is still free to change —
> which is why `database_destination` was added the moment the module was designed rather than when
> it shipped: **adding it now is free and adding it after the first licence is issued is not.**

The mechanism behind "not free" is `licensing/features.py:47`:

```python
ceiling = SELLABLE_FEATURE_KEYS if license_features is None else frozenset(license_features)
```

- A licence signed with `features: null` grandfathers every sellable key, so a key added later
  reaches it automatically.
- A licence signed with an **explicit list** does not. Every such customer would silently lack the
  new key until someone reissued their code — with nothing anywhere to say so.

Explicit lists are not hypothetical: issuing one is the whole point of `--features`, and one was
issued on this machine on 2026-08-26 for feature-gating tests
(`load_profile,billing,database_destination`).

So the window in which this is a one-line change closes the first time a customer licence is
signed, and nobody will get a warning when it does.

## What must NOT change

**Reserving a key is not shipping a feature.** As of today the File Upload Destination is a
presentation-only shell:

- `web/src/pages/FileUploadDestination.tsx` is 89 lines and its own docstring says *"There is no
  transport behind this page: the Data-out module (SPEC §3.8) has not shipped, so nothing typed
  here is saved, sent, or read back."*
- The page still renders *"Nothing typed on this page is saved, sent, or stored."*
- `grep -rn "file_upload\|fileUpload" app/src/arichds/ --include=*.py` returns **nothing** — there
  is no endpoint, no settings row, no job.

A customer who bought this key today would be buying a form that discards what they type. So:

- **No route gains `require_feature("file_upload_destination")`** — there is no route.
- **The page's own text and behaviour are untouched.**
- **Issue 012's decision D7 stands**: File Upload stays *not advertised* in the nav. Reserving the
  key removes one of D7's two stated reasons ("no feature key"), not its conclusion — the
  conclusion rests on the other reason, that there is nothing behind the page. 012's `features.ts`
  mapping keeps `kind: "never"`, and this issue amends **only the sentence in that file and in
  `AppShell.tsx`'s docstring** that says File Upload has no feature key, so the two records do not
  contradict each other.

## Where the key must reach

The key is inert but it is not free of consequences — several places count or enumerate the set,
and the count changes:

- `app/src/arichds/constants.py` — the frozenset, and the comment above it, which currently says
  "Ten sellable keys" and names `database_destination` as the last addition. Extend it the way #46
  extended it, naming this issue and the reserve-not-sell intent.
- `tools/arichds_vendor.py` — issue 010 made `sign --features` validate against
  `SELLABLE_FEATURE_KEYS` **by import**, so the vendor CLI accepts the new key with no edit.
  Confirm that by running it rather than assuming; the identity test
  (`test_vendor_sign_features.py`) should also still pass unchanged.
- `web/src/features.ts` (issue 012) — `FEATURE_LABELS` must cover **all** of `FEATURE_KEYS`, so it
  needs an English label. `PAGE_ENTITLEMENT` keeps File Upload at `"never"` per D7 above.
- `app/tests/test_nav_feature_contract.py` (issue 012) — the cross-language tripwire asserts every
  key has a label; it will fail until the label exists, which is the tripwire doing its job.
- `SPEC.md` §3.9 — says ten sellable keys. Now eleven.
- Anything else that hardcodes the number. **Search for it rather than trusting this list**: issue
  #46 found stale "nine sellable" prose after adding the tenth key, and the same sweep is owed
  here. Search all file types including dot-directories.

## Acceptance criteria

- [ ] `file_upload_destination` is in `SELLABLE_FEATURE_KEYS`; `FEATURE_KEYS` still derives from it
      and needs no edit
- [ ] The comment above the frozenset records the eleventh key, this issue, and that it is
      **reserved, not sellable yet** — so nobody quotes it to a customer
- [ ] `tools/arichds_vendor.py sign --features "file_upload_destination"` is accepted, proven by
      running it and decoding the payload — not by reading the import
- [ ] No route anywhere gains a `require_feature("file_upload_destination")`, proven by grep
- [ ] `web/src/pages/FileUploadDestination.tsx` is byte-identical
- [ ] The File Upload nav entry is still hidden for every licence shape, including one that
      **grants** `file_upload_destination` — a test or the render evidence proves it, because this
      is the one thing a reader will expect the key to change and it must not
- [ ] `features.ts` and `AppShell.tsx` no longer say File Upload has no feature key; both say the
      key is reserved and the page is unadvertised until M8 gives it a transport
- [ ] Every place that counts the keys is updated — found by a repo-wide sweep whose command is
      pasted in the report, not by trusting this issue's list
- [ ] Required tests are derived as a **mutation table** — one row per decision, each naming the
      mutation that turns it red — and each mutation is actually run
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `python -m pytest -n auto` in `app/`
      (use `python -m pytest`; the console script under-collects — `docs/issues/004`), and
      `pnpm lint` (**zero** problems) + `pnpm build` in `web/`
- [ ] **Output Parity vs v1** is not applicable — v1 had no feature entitlement. Say so rather than
      inventing a comparison

## The question this issue does not answer

**What the key will actually gate when M8 ships**, and whether the File Upload Destination is one
sellable thing or several (FTP vs FTPS vs SFTP, ADR 0016 leaves the transport open). Reserving one
key assumes one. If M8 concludes otherwise the key set changes again — which is affordable exactly
as long as no customer licence has been signed, and this issue does not extend that window.

## Blocked by

**Issue 012 must be committed first.** It creates `web/src/features.ts` and
`app/tests/test_nav_feature_contract.py`, both of which this issue edits, and it is what makes
`FEATURE_LABELS` exhaustive over `FEATURE_KEYS`. Running the two concurrently on one working tree
would collide on the same files.
