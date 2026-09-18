# The File Upload Destination cannot be switched off from the page once a tab has been saved

**Type**: AFK · **Status**: ready-for-agent · **Found**: 0.7.0 verification walk on the installed
build, 2026-09-18 · **Grilled**: 2026-09-18 with the owner (nine decisions, all recorded below —
do not re-open them) · **Blocks**: the 0.7.1 delivery build · **Blocked by**: nothing

## The problem

ADR 0025 says, in its Consequences: *"there is no switch because an empty page **is** the switch,
the same rule the Central Push follows."* Both sibling destinations honour that rule after the first
save as well as before it — the Central Push page says "Leave the URL empty to send nothing" and
`api/central_push.py` does not validate the URL; the Database page says "The sync is off while Host
is empty" and `api/settings.py`'s save accepts an empty host. **The FTP page is the one that does
not**: once any tab has been saved there is no way back to "empty" from the page —

- `PUT .../https` refuses a blank URL (ticket 01's own rule, `api/file_upload.py`
  `put_file_upload_https`: `"url is required."`).
- `PUT .../sftp` refuses a save with neither a password nor a key-file path **regardless of whether
  a host is present** (`put_file_upload_sftp`).
- `web/src/pages/FileUploadDestination.tsx` marks Host/URL `required: true` on all three tabs, so
  the page never sends an empty one — even though `PUT .../sftp` and `PUT .../ftps` would accept it
  and `fileupload/cycle.py::_active_configured()` would then correctly report `not_configured` and
  never touch a transport.

So after the first save the `file_upload` job keeps connecting every fifteen minutes, logging one
WARNING per failed cycle, until the operator points it at a working server or edits `arichds.db`
by hand. Pausing every device does not help — the cycle uploads files already on disk.

*Correction found while implementing (2026-09-18)*: the grill's premise that the Database page
"does have an off switch" was true of its **API** only — `web/src/pages/DatabaseDestination.tsx`
marks Host `required` exactly as this page did, while its own text says "The sync is off while
Host is empty". Same class of bug, one line; filed as `docs/issues/023` rather than widened into
this ticket.

Two smaller things in the same area, folded in because they are the same three lines of the page:

- The three **Test connection** buttons test the *saved* values (`POST .../{sftp,ftps,https}/test`
  take no body), while the SFTP tab's Host-key helper says "press Test connection to see the
  server's key" as if the form values were used. The Database page names the same behaviour
  honestly: **Test saved connection**.
- The status card's `not_configured` copy ("The last cycle found this destination not configured —
  an active protocol needs a host or URL … Save a tab above") is written for someone who has never
  configured the page; once clearing the host is the way to stop, the same card must read correctly
  for someone who did that on purpose.

## The decision (grilled 2026-09-18)

1. **Make ADR 0025's sentence true for the whole life of the page, not only before the first
   save**: *an empty host/URL on the active tab means off*, savable from the page. **No new
   endpoint, no new state, no change to the cycle** — `_active_configured()` and the
   `not_configured` outcome already are the off state. (Option "Stop uploading button + endpoint"
   rejected: it contradicts the ADR's "there is no switch" and adds a state the siblings lack.)
2. **An empty tab may be saved only when it is the active tab.** Saving an empty tab that is *not*
   the active one — including when nothing is active yet, `active_protocol == ""` — is a 422 that
   names the way out. Reason: "Save makes that tab active" stays an exception-free rule, and an
   operator exploring the FTPS tab while SFTP is uploading cannot silently stop the uploads with
   one stray click. A fresh machine keeps exactly today's behaviour (the form blocked it; now the
   API does).
3. **Clearing the host keeps everything else**: password, token, passphrase, key-file path and the
   pinned host-key fingerprint all stay, under the existing omit-keeps rule — switching back on is
   typing the host and pressing Save. A later *different* server is caught by the existing
   `HostKeyMismatchError` / "changed key, press Pin" path (ticket 04); no special case.
4. The SFTP "password or key file" rule applies **only when the host is non-empty**.
5. The cycle outcome stays `not_configured` (API shape and contract unchanged); the card's copy for
   it becomes neutral so it reads correctly both for "never configured" and "cleared to stop".
6. Buttons → **Test saved connection** ×3; the Host-key helper says the server's key is shown by
   Test saved connection after the tab is saved.
7. ADR 0025 is **amended in place** (one paragraph in Consequences citing this issue), not reversed
   — the decision stands, the implementation had narrowed it.
8. Ship as **0.7.1**: `installer/arichds.iss` `AppVersion` bump is part of this issue; the build is
   the owner's step afterwards (`/build-exe installer`).
9. Before delivery, as one local ticket via `/run-issue`.

## What to do

### API — `app/src/arichds/api/file_upload.py`

- Introduce one helper the three `PUT` handlers share, e.g. `_refuse_empty_unless_active(session,
  protocol, value, field)`: strip *value*; if it is empty and `load_config(session).active_protocol
  != protocol`, raise 422 with a detail that names the way out, in this shape (the reviewer holds
  the wording to the *meaning*, not the letters):
  `"Fill in a host to switch uploads to SFTP, or clear the host on the active tab to stop them."`
  (for HTTPS: "Fill in a URL to switch uploads to HTTPS, …"). When nothing is active yet the same
  message applies — "start" rather than "switch" is fine but not required.
- `put_file_upload_https`: replace the unconditional `"url is required."` refusal with the helper.
- `put_file_upload_sftp`: call the helper first; apply the existing "Provide either a password or a
  key file path." rule **only when the stripped host is non-empty**.
- `put_file_upload_ftps`: call the helper (today it has no host check at all).
- Store the **stripped** host/URL. Every other field keeps its current omit-keeps / empty-clears
  semantics — this issue changes no credential handling and never touches
  `FILEUPLOAD_SFTP_HOSTKEY_FINGERPRINT_KEY` (still written only by `POST .../sftp/host-key`).
- Docstrings of the three handlers say the rule in one sentence each and cite ADR 0025.

### Web — `web/src/pages/FileUploadDestination.tsx`

- Drop `required` from the Host (SFTP, FTPS) and Server URL (HTTPS) `Form.Item`s. Port stays
  required (it is prefilled). Keep the placeholders.
- Rename the three buttons to **Test saved connection**.
- Host-key helper: `Not pinned yet — save the tab, then press Test saved connection to see the
  server's key.`
- Status card, `not_configured` branch — neutral copy covering both cases, e.g.:
  `Nothing was sent — the active tab has no host or URL. Leave it empty to keep uploads off, or fill
  it in and save to start; then press Upload now or wait for the next scheduled cycle.`
- How-to (the shared "Before you save" / "What this machine will create" / "Not supported" block or
  the page intro, whichever reads better): one sentence — *To stop uploading, clear the host (or URL)
  on the active tab and save; the other fields stay so you can switch back on with one save.*
- Surface the new 422 detail through the existing `surface()` error path — nothing new to build,
  just confirm by eye that the message reaches the toast.
- English only. Invoke the `antd-ui` skill before editing.

### Docs

- `docs/adr/0025-*.md` → Consequences: add one paragraph after the "empty page is the switch" bullet:
  the rule holds for the whole life of the page — an empty host/URL on the *active* tab is the off
  state, savable from the page, with the "only the active tab may be saved empty" guard and the
  keep-everything-else rule; cite `docs/issues/022`. Do not touch the Decision section.
- `CLAUDE.md` ADR 0025 digest: one sentence recording the same, at the end of the ticket 01
  paragraph (the one that says the HTTPS tab is refused with no URL — that sentence must be
  corrected, not left contradicting the code).
- `installer/arichds.iss`: `AppVersion "0.7.0"` → `"0.7.1"`.
- No `CONTEXT.md` change: no new term — "off" is ADR 0025's own "empty page".

## Acceptance criteria

Required tests are derived as a **mutation table** — one row per decision above, each naming the
mutation that turns it red — and every mutation is actually run and reported.

- [ ] `PUT .../sftp` with a blank host **while SFTP is active** → 200, `active_protocol` still
      `"sftp"`, stored host empty; the stored password, key path, passphrase and pinned fingerprint
      are unchanged (assert each one by reading it back; the fingerprint via `GET`).
      *Mutation*: drop the "active tab" exemption → red.
- [ ] Same for `PUT .../ftps` (blank host, FTPS active) and `PUT .../https` (blank URL, HTTPS
      active — the existing `test_a_blank_url_is_refused` is **renamed and inverted** for this case;
      its refusal half moves to the next row).
- [ ] `PUT .../https` with a blank URL while **SFTP** is active → 422, detail names HTTPS and the
      way out; `active_protocol` still `"sftp"`, SFTP settings untouched.
      *Mutation*: make the helper always accept → red.
- [ ] `PUT .../ftps` with a blank host while **nothing** is active (`""`) → 422; `active_protocol`
      still `""`. *Mutation*: treat `""` as "no active tab, so allow" → red.
- [ ] `PUT .../sftp` with a blank host, no password and no key path, SFTP active → 200 (the
      credential rule no longer fires on an empty host). *Mutation*: apply the credential rule
      unconditionally → red.
- [ ] `PUT .../sftp` with a **non-empty** host, no password and no key path → still 422
      (`test_neither_password_nor_key_path_is_refused` stays green, unchanged).
- [ ] A whitespace-only host is stored as empty and judged as empty (`"   "` behaves as `""` in
      both the 200 and the 422 rows). *Mutation*: drop the strip → red.
- [ ] After clearing the active tab's host, `file_upload_cycle()` publishes
      `outcome == "not_configured"` and **never builds a transport** — assert with a `_build_transport`
      spy/monkeypatch that it is not called (the existing `test_fileupload_cycle.py` fixtures already
      drive a cycle with an injected transport; this test injects none and proves none is built).
      *Mutation*: make `_active_configured` return True for an empty host → red.
- [ ] `TestTheResponseNeverCarriesASecret` and `TestFeatureGate` stay green unchanged.
- [ ] Web: `pnpm lint && pnpm build` pass; by eye on `pnpm dev` (or the built SPA served by
      `fastapi dev`): the three buttons read **Test saved connection**, Host/URL can be cleared and
      saved on the active tab, the toast shows the API's 422 message when saving an empty non-active
      tab, and the status card shows the new neutral copy after Upload now.
- [ ] `docs/adr/0025-*.md` Consequences paragraph and the `CLAUDE.md` digest sentence are in the
      same change; the digest's "refused with no URL" wording no longer contradicts the code.
- [ ] `installer/arichds.iss` says `0.7.1`. No PyInstaller/installer build inside this ticket —
      the owner runs `/build-exe installer` afterwards.
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `pytest -n auto` in `app/` (foreground,
      no pipe — the run was killed silently once by `| head`), plus `pnpm lint && pnpm build` in
      `web/`. Scoped runs during the loop stay plain (`pytest tests/test_fileupload_config_api.py`).
- [ ] **Real-meter read / Output Parity**: not applicable — no acquisition or export code is
      touched; say so in the report rather than claiming a read.

## Testing seam

`app/tests/test_fileupload_config_api.py` (`TestPutSftp` / `TestPutFtps` / `TestPutHttps` — add a
`TestSavingAnEmptyTab` class rather than scattering rows) and one test in
`app/tests/test_fileupload_cycle.py` for the no-transport row. The web has no test runner; the
lint/build gate plus the by-eye list above is the seam, as every earlier `web/` ticket used.

## What this issue does not do

- **No Stop button, no `active-protocol` endpoint, no new cycle outcome** — decided against
  (decision 1 and 5).
- **Does not clear credentials or the pinned host key** when the host is cleared (decision 3).
- **Does not change what Test saved connection tests** — it still uses the stored values; only the
  label and helper change.
- **Does not touch `docs/issues/020` or `021`** — the redaction gap and the plain-`http://` URL are
  separate decisions the owner still owns.

## Evidence

- `docs/adr/0025-*.md` Consequences, the "empty page is the switch" bullet.
- `app/src/arichds/api/central_push.py:102` (URL not validated) and `app/src/arichds/api/settings.py:341`
  ("Empty means not configured") — the two siblings' off rule.
- `app/src/arichds/api/file_upload.py` — `put_file_upload_sftp` / `put_file_upload_ftps` /
  `put_file_upload_https`; the body-less `test_file_upload_*` endpoints.
- `app/src/arichds/fileupload/cycle.py` — `_active_configured()` and the `not_configured` branch.
- `web/src/pages/FileUploadDestination.tsx` — Host/URL `required: true` on the three tabs; the
  Host-key helper; the three Test connection buttons; the status card's `not_configured` branch.
- Seen on the installed 0.7.0 (2026-09-18): with nothing saved, Test connection answers
  "No host is saved yet. Save the SFTP tab first."; the status card reads "The last cycle found this
  destination not configured".
