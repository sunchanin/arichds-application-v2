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

---

## Fixed 2026-09-11 — and the numbers above had gone stale in the worse direction

`app/pyproject.toml` now reads `pythonpath = ["src", "."]`. One line, as prescribed. The
five `from tests.conftest import ...` modules were not touched.

Verified from `app/`, all three invocations agreeing for the first time:

```
.venv/Scripts/pytest.exe --collect-only -q          ->  2163 collected, 0 errors
.venv/Scripts/python.exe -m pytest --collect-only   ->  2163 collected, 0 errors
.venv/Scripts/pytest.exe -n auto                    ->  2106 passed, 57 skipped in 143s
```

**Two corrections to this issue as filed.** The counts above (1395 / 1494, "99 fewer") were
true in August and were not true by September: the number had grown to **2024 vs 2163**, and
a sixth module had joined the five (`test_feature_entitlement.py`). More importantly the
failure mode had changed. This issue says the run "fails loudly ... so nothing has shipped
against a green run that was secretly short" — by 2026-09-11 the documented gate did not run
at all. It ended with `Interrupted: 6 errors during collection`, so the loudness had become a
refusal. The reassurance in "Why it matters" was therefore describing a milder bug than the
one that was sitting there.

The gate numbers reported when M13 closed (**2106 passed, 57 skipped**) match the full 2163
collection exactly, so no phase shipped against a short run. What shipped short was the
*instruction*: every issue after this one was told to run a command that could not work, and
nine of them pasted a workaround into their acceptance criteria instead. Those notes are
removed from the five issues still open (005, 006, 007, 008, 014). The four already fixed
(013, 015, 016, 017) keep theirs: they record what was true when they ran, and rewriting a
closed record is the failure ADR 0013 is about.
