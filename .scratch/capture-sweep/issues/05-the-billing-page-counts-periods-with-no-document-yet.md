# 05: The Billing page counts the periods with no document in this folder yet — and installer 0.8.4

**What to build:** Above the Save all button the Billing page says "N closed period(s) have no
document in this folder yet — press Save all." whenever N is non-zero, and nothing when it is
zero. N comes with the billing settings response as `captures_missing`: the number of closed
periods whose *Captured* stamp is empty **or** earlier than the moment the Billing Folder setting
was last saved (the settings row's own updated time), so a moved folder shows the right number
rather than zero; it is zero while the folder is empty. It is a hint, not a folder walk: the sweep
is the authority on what is missing. The page re-reads the count when a sweep finishes, so the
sentence disappears on a complete folder. The batch ships as installer 0.8.4.

**Blocked by:** 04 (Save all — the sentence names it and the page re-reads after its sweep)

**Status:** done (2026-09-23)

- [x] `captures_missing` on the billing settings response, counted in the database (never by
      walking the folder): empty `captured_at` counts; a `captured_at` older than the folder
      setting's updated time counts once the folder is saved again; a newer one does not; zero
      with the folder empty; the exact-dict test of the settings response is extended
- [x] The page renders the sentence for every role when the count is non-zero, none when zero,
      and re-fetches the settings when the sweep's status turns from running to finished
- [x] `AppVersion` moves to 0.8.4; the onedir and the installer are built and the setup file's
      SHA256 and size are reported to the owner; the report carries the upgrade note (an install
      with only the Load Profile folder set stops getting a billing file and an Energy file until
      their folders are set)
- [x] Gate: `ruff format --check`, `ruff check`, `pytest -n auto` (app), `pnpm lint && pnpm build`
      (web)

**Evidence:** `captures_missing` on `GET /api/billing/settings` (`_captures_missing_count`: captured_at NULL or
< the capture_dir settings row's `updated_at`, coerced to UTC; 0 while the folder is empty); the page's
sentence for every role, re-read when the sweep finishes. Tests `TestCapturesMissing` (4) + exact-dict test.
Review round (reviewer agent, APPROVED_WITH_FIXES): fix 1 a crashed slice ends the sweep; fix 2 a document
already present stamps Captured from its mtime (else an upgraded site counts forever); fixes 3/4 texts.
Nits 5/6 left as noted. Full gate after the fixes: 2641 passed, 77 skipped (`pytest -n auto`); ruff green;
`pnpm lint && pnpm build` green. Installer `installer\Outputrichds-setup-0.8.4.exe`, 38,148,768 bytes,
SHA256 f34b7e79914356e9703ab19748763545519d61a680ae0d0795692dd61a17d2a4 (built from this tree).
Upgrade note: an install that set only the Load Profile folder stops getting a billing file and an
Energy file until their folders are set; the top-level billing file is left for the owner to remove.
