# The capture directory is an operator setting; the backup directory is not

Status: accepted (2026-08-09, owner decision during M6 grilling). **Fully implemented** — the
`settings` table, `capture_dir` validation/API/form, the two renderers, the hardened write and
the render-on-miss download all landed with issue #22/M6b.

Reverses nothing. This ADR exists because two v2 decisions about "where does the program write
a file" landed on **opposite** answers, and the difference is not visible from either one alone.

## The inconsistency a future reader will find

`CONTEXT.md`, on Daily Backup, is categorical:

> *"It sits on the same disk as the original… **The destination is fixed, not a setting.**"*

M6 then adds `capture_dir` to `settings`, editable by an admin through the Billing page, and
with it the whole apparatus that a user-supplied write path requires: reject `..`, resolve
symlinks, `lstat` the final component for `S_ISLNK` before `os.open(O_NOFOLLOW)` to close the
TOCTOU window, stepwise `os.mkdir(mode=0o700)` rather than `mkdir(parents=True)`. In v1 that is
`billing/paths.py`, 146 lines that exist for no other reason.

Read either decision on its own and it is obviously right. Read them together with no
explanation and the only available conclusion is that someone was inconsistent — and the
cheapest "fix" is to make capture match backup, delete 146 lines, and quietly break the feature.

## They differ because the artifacts have different readers

A **backup** is written for the machine. Its only consumer is a restore, performed by whoever
is holding the incident, and that person is already at a command prompt. Letting an operator
choose where it goes adds a way for backups to end up somewhere nobody looks, in exchange for
nothing — so the destination is fixed and the ADR-level cost is zero.

A **capture** is written for a person, and specifically for a person who is going to hand it to
someone else. The requirement it comes from says so — v1 ADR 0003 quotes the mockup directly:

> *"แคปรูปมีเป็นรูปในโฟเดอร์ที่เก็บและ**สามารถส่งไปให้ลูกค้าเลย**"*
> *"แคปรูปแคปแบบ**ไม่ต้องเปิดหน้าเว็บ**หรือโปรแกรมได้มั้ย"*

The folder **is** the handoff mechanism. Not a storage location — the place the operator's
existing workflow already reaches: a network share, a synced folder, the directory their mail
client opens onto. A fixed path under `%ProgramData%` satisfies the letter of "there is a
folder" while defeating the sentence it came from, because the operator would have to go and
fetch from it every time.

The distinguishing question, for anyone weighing a third case later: **does a human carry this
file somewhere?** If no, fix the path. If yes, the path is theirs.

## Decision

- `capture_dir` is a key in the `settings` table, edited by an admin on the Billing page. M6 is
  the first module that needs `settings`, so M6 creates it.
- The full path-validation apparatus comes over from v1 `billing/paths.py`. It is not optional
  and it is not "hardening we can add later" — it is the price of the previous bullet.
- **Changing `capture_dir` orphans existing captures, by design**, exactly as v1 ADR 0008
  decided: no move, no copy, no block. The path is derived from convention on every request, so
  old files simply stop being reachable through the UI. The Save button warns first when the
  device set already has captures.
- The backup destination stays fixed. Nothing in this ADR touches it.

## What we do *not* carry over from v1

- **No `billing_captures` table.** It never existed in v1 either — v1 ADR 0003 decided
  *"ไม่เก็บ path ใน DB — derive จาก convention ทุกครั้ง"* and held that line even when ADR 0008
  reconsidered it. v2's `SPEC.md` §4 had counted such a table among its twelve; the count is
  now eleven.
- **No regenerate endpoint.** v1 needed `POST /capture/{id}/regenerate` (its ADR 0009) because a
  failed `BackgroundTask` left a permanently missing file with no other way back. v2 renders
  synchronously after the row commits, and the download endpoint **renders on a miss** and
  writes the result — so a capture that failed, or a file an operator deleted, repairs itself
  the moment someone asks for it. That also removes v1's other artifact: the two-second retry
  the frontend had to perform because the response returned before the file existed.
- **No Thai font.** The document is English. Operator-entered values that are not ASCII are
  replaced and logged once per name, as v1 does. This is a deliberate limitation, not an
  oversight: a site whose `site_name` is Thai gets `?` in that field.

## Consequences

- This is **the only place the shipped product writes outside `%ProgramData%\ARICHDS`**. Every
  other artifact — the database, the license, the logs, the backups — is at a fixed path. That
  makes `capture_dir` the product's entire untrusted-path surface, and the reason the
  validation in `paths.py` is load-bearing rather than defensive.
- An admin who edits the database directly, bypassing the API, gets no validation and no
  warning. v1 accepted this on the grounds that direct DB editing is outside the threat model,
  and so do we.
- **Do not "make these consistent."** If a later change removes `capture_dir` in the name of
  matching Daily Backup, it removes the mechanism the customer asked for by name, and the 146
  lines that go with it will look like dead weight on the way out.
