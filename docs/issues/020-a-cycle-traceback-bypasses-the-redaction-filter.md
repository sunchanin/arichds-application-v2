# A Destination cycle's `logger.exception` puts the raw exception past the redaction filter

**Type**: AFK · **Found**: file-upload ticket 02, 2026-09-16 — the implementer's own log test went red
on the same pattern copied from `centralpush/cycle.py`, and the reviewer confirmed the original is
still live · **Blocks**: nothing shipped; it is a latent credential-leak vector in the App Log

## The problem

`CredentialRedactionFilter.filter()` rewrites only `record.msg` (after `getMessage()`) and clears
`record.args`. It never touches `record.exc_info`. When a handler formats a record that carries
`exc_info`, the traceback — including `str(exc)` — is appended **after** the filtered message,
unredacted.

Two shipped cycles log their generic-failure branch with `logger.exception(...)`, which attaches
`exc_info`:

- `app/src/arichds/centralpush/cycle.py:208` — `logger.exception("Central Push cycle failed")`.
  `error` itself is correctly the class name only, so the status card is clean; the log line is not.
- `app/src/arichds/dataout/sync.py:180` — `logger.exception("Database Destination cycle failed")`,
  and here the status is not clean either: `error = f"{type(exc).__name__}: {exc}"` carries the
  driver's message into the in-memory status that `GET /api/settings/database-destination` returns.

Whether a secret actually reaches a line depends on what the driver or `urllib` puts in the
exception text. PyMySQL's `OperationalError(1045, "Access denied for user 'root'@'localhost' (using
password: NO)")` names the user and host, not the password; a proxy or a mis-typed URL can put a
`user:password@host` string into a `URLError`. The invariant in `CLAUDE.md` ("Credential redaction
filter on every log handler") is meant to make that question moot, and today it does not.

`app/src/arichds/fileupload/cycle.py:396-402` is the corrected shape, landed with file-upload ticket
02: `logger.warning("… ended skipped — %s", error)` with `error = type(exc).__name__`, and a test
(`test_fileupload_cycle.py::TestLogging::test_a_secret_never_reaches_the_status_or_the_log`) that
raises an exception whose message carries a secret and asserts it reaches neither the status nor
`caplog` (message *or* `exc_info`).

## What to do

Either fix, not both:

1. **Per site** (smallest): switch both `logger.exception` calls to `logger.warning` with the class
   name, and make `dataout/sync.py`'s `error` the class name only (the page loses the driver's
   message — check `DatabaseDestination.tsx` for anything that parses it). Copy the fileupload test
   to `test_central_push_cycle.py` and `test_dataout_sync.py`.
2. **In the filter** (closes the class): make `CredentialRedactionFilter.filter()` also redact the
   formatted traceback — render `exc_info` once with `logging.Formatter.formatException`, run
   `redact()` over it, store it in `record.exc_text` and set `record.exc_info = None` so the handler
   prints the redacted text. Then `logger.exception` stays usable everywhere. Add a test that logs
   with `exc_info` carrying `password=…` and asserts the handler's output is redacted.

Option 2 is the one that matches the invariant's wording; option 1 is what ticket 02 did locally.
Whichever is chosen, `CLAUDE.md`'s invariant bullet should say whether tracebacks are covered.

## Evidence

- `app/src/arichds/logging_config.py:77-85` — the filter body.
- `.claude/run-logs/issue-file-upload-02.md` — the round-1 review that ruled the site out of scope
  and asked for this file.
