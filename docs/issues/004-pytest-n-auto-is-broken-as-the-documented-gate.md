# `pytest -n auto` under-collects by 99 tests — and it is the documented gate

**Type**: AFK · **Found**: review of issue #36, 2026-08-22 · **Blocks**: nothing, but affects every issue after it

## The problem

`CLAUDE.md` → Commands documents the module gate as `pytest -n auto`. Run through the
console script, that command **silently collects 99 fewer tests than the suite contains**:

```
app/.venv/Scripts/pytest.exe --collect-only -q   →  1395 tests collected, 5 errors
python -m pytest --collect-only -q               →  1494 tests collected, clean
```

Each of the five errors is `ModuleNotFoundError: No module named 'tests'`.

## Root cause — exact, verified

- `app/pyproject.toml:67` sets `pythonpath = ["src"]` and **not** `"."`
- there is no `app/tests/__init__.py`
- five test modules import `from tests.conftest import …` — `test_api_users.py:19`,
  `test_api_license_auth.py:16`, `test_auth_logging.py:13`, `test_license_roundtrip.py:35`

`python -m pytest` prepends the current directory to `sys.path`, so those imports resolve.
**The `pytest.exe` console script does not**, so they fail at collection.

## Why it matters

It fails **loudly** — the errors are printed, so nothing has shipped against a green run that
was secretly short. That is the only reason this is not urgent. But an agent reading
`CLAUDE.md` runs the documented command, sees errors it did not cause, and has to decide
whether they are its problem. Two issues in a row have now spent effort on that.

## The fix

```toml
pythonpath = ["src", "."]
```

One line in `app/pyproject.toml`.

## Acceptance criteria

- [ ] `app/.venv/Scripts/pytest.exe --collect-only -q` collects the same count as
      `python -m pytest --collect-only -q`, with zero errors
- [ ] `pytest -n auto` from `app/` passes clean, invoked exactly as `CLAUDE.md` writes it
- [ ] The five `from tests.conftest import …` modules are untouched — the fix is the path
      configuration, not the imports
- [ ] `ruff format --check .` · `ruff check .` pass
- [ ] If the fix turns out to need more than the one line, say why in the PR rather than
      widening it silently

## Blocked by

None - can start immediately.
