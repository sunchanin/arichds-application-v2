# Capture folders are created unreadable to the operator, so Syncthing cannot ship them

**Type**: AFK · **Found**: customer site, 2026-09-01 · **Blocks**: nothing · **Blocked by**: nothing

## The symptom

Syncthing on the customer machine cannot scan a capture folder:

```
billing\002607000049    scan: open \\?\C:\Users\logger\Desktop\data\billing\002607000049:
                        Access is denied.
```

The Load Profile CSV folder beside it syncs normally. Only billing captures fail.

## Root cause, proved rather than reasoned

`capture/write.py:73` creates each missing ancestor with an explicit mode:

```python
os.mkdir(str(directory), 0o700)
```

`os.mkdir`'s own docstring says *"The mode argument is ignored on Windows"*. **That is wrong for
`0o700`**, which CPython special-cases. Measured on this machine, Python 3.14.6:

| created by | resulting ACL |
|---|---|
| `os.mkdir(p, 0o700)` | `SYSTEM`, `Administrators`, `OWNER RIGHTS` — inheritance replaced |
| `os.mkdir(p)` | `SYSTEM`, `Administrators`, **the user** — inherited from the parent |

The service runs as **LocalSystem** (ADR 0017, issue #40), so the owner is `SYSTEM` and the
resulting folder grants `SYSTEM` and `Administrators` and nobody else. Syncthing runs as the
`logger` user. It is denied, exactly as reported.

The asymmetry with Load Profile is the same fact from the other side —
`export/csv_export.py:272`:

```python
final_path.parent.mkdir(parents=True, exist_ok=True)     # no mode -> inherits
```

Two output paths, both writing into a directory the operator chose, disagreeing about who may
read the result. `export/` is the one that is right.

## Why this is a defect and not hardening working as intended

ADR 0010's whole premise is that **a capture is a document a human carries to a customer**, which
is why `capture_dir` is an operator setting at all while the backup directory is fixed. A folder
the operator cannot read defeats the reason the setting exists.

Issue #22's hardening is about not being tricked into writing somewhere else — the allowlist
check, the `lstat` symlink guard, `O_EXCL|O_NOFOLLOW`, the unlink-the-partial. **None of that
depends on the directory mode.** The `0o700` reads as POSIX habit, correct for a service's own
private state directory and wrong for a directory whose entire purpose is that somebody else picks
it up.

Memory records that the delivery mechanism for these files is Syncthing, not code
("CSV to machine B is Syncthing, not code"). A sync agent runs as a user. So does the operator
double-clicking the folder.

## What to do

**D1 — create capture directories without an explicit mode, so they inherit the operator-chosen
parent.** One character class of change at `write.py:73`. The parent is the operator's stated
intent; inheriting it is what `export/` already does and what nobody has had to work around.

**D2 — leave `_atomic_write`'s `0o600` alone, and say why in the docstring.** On Windows a file's
mode only drives the read-only attribute; its ACL is inherited from the containing directory, so
once D1 lands the files are readable to whoever the folder is readable to. Changing it would widen
the diff for no effect on the platform this ships on. Record the POSIX caveat rather than fixing a
platform the product does not run on.

**D3 — the docstring's step 3 currently reads `Stepwise os.mkdir(..., 0o700)`.** It has to change
with the code, and it is the right place to record *why* there is no mode: a future reader adding
one back would reintroduce this exactly.

**D4 — existing folders keep their ACL.** `os.mkdir` is only called for a directory that does not
exist, so nothing repairs `002607000049` on the customer machine. Do **not** make the app rewrite
ACLs: a service silently re-permissioning a directory under a user's Desktop is a worse surprise
than the bug. The operator command belongs in `installer/README.md` instead:

```powershell
icacls "<capture_dir>" /inheritance:e /T
icacls "<capture_dir>" /grant "<user>:(OI)(CI)F" /T
```

## Acceptance criteria

- [ ] `capture/write.py` creates directories with no explicit mode
- [ ] A test proves a **newly created** capture folder is readable by a non-administrator — assert
      on the ACL, not on the mode argument. `icacls` output or `win32security` both work; if
      neither is available in the test environment, assert that `os.mkdir` is called with no mode
      argument **and** say in the report that the ACL itself is unpinned, rather than pretending
      an argument assertion covers it
- [ ] The mutation `os.mkdir(str(directory))` -> `os.mkdir(str(directory), 0o700)` turns that test
      red. This is the whole issue; a test that survives it proves nothing
- [ ] Every existing guarantee in `write_capture` still holds, each with the test that already
      covers it named in the report: allowlist rejection, symlink parent rejection, `O_EXCL`
      refusing a second write, nothing on disk after a render failure, nothing on disk after a
      partial write
- [ ] `write.py`'s module docstring step 3 no longer says `0o700` and records why there is no mode
- [ ] `installer/README.md` gains the operator command for folders created before this fix
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `python -m pytest -n auto` in `app/`
      (use `python -m pytest`; the console script under-collects — `docs/issues/004`)
- [ ] **Real-meter read**: not applicable, nothing here touches acquisition. Say so
- [ ] **Output Parity vs v1**: not applicable — v1 wrote captures as a user-session process, so it
      never had this failure mode to compare against. Say so

## What this issue does not do

- **It does not touch `export/`.** That path is already correct and is the model being copied.
- **It does not repair the customer's existing folders.** D4 — that is an operator command, run
  once, deliberately.
- **It does not revisit ADR 0017's LocalSystem decision.** The service running as LocalSystem is
  what makes the owner `SYSTEM`, but moving the service was already tried and reverted once
  (issue #40 correcting issue #38's own fix), and the directory mode is the actual cause.
