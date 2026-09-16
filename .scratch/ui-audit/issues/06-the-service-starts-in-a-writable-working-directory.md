# 06: The service starts in a writable working directory

**What to build:** Starting the installed service never fails a poll with
`PermissionError: [Errno 13] Permission denied: 'logFile.txt'`. The vendored Gurux reader
opens a log file relative to the current working directory, and under the service that
directory is `Program Files` (or `System32`), which LocalSystem-run code is not meant to
write into. The vendored `GX*.py` files are copied from v1 verbatim and are never edited
(CLAUDE.md), so the fix is the process's working directory: the application makes it a
writable path under its own data directory at startup, so both the installed service and
`fastapi dev` are covered without an installer step.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] At startup, before the first driver is constructed, the process changes its working
      directory to a writable directory under the configured data dir (the existing `logs`
      or `tmp` directory — pick one and say why in the code comment). Test: after startup
      `os.getcwd()` is under `settings.data_dir`. Mutation probe: removing the chdir turns
      it red.
- [ ] Nothing else in the application resolves a path relative to the working directory
      (grep for bare relative opens; every app path is already absolute via `settings`).
      A test guards the one known relative write by constructing a reader and asserting its
      log file lands under the data dir.
- [ ] The installer README's "Upgrading" section notes where the Gurux log file now lives.
- [ ] After a rebuild and reinstall on the dev machine, the first minute of the App Log
      after "Scheduler started" contains no `PermissionError`.
- [ ] Gate: `ruff format --check .` + `ruff check .` + `pytest -n auto` green in `app/`.
