# ARICHDS — backend

One process serving the REST API, the built web UI, and the meter Poller
(SPEC §4). Python 3.14 (floor `>=3.13`), FastAPI, SQLAlchemy 2, SQLite (WAL), Alembic.

## Layout

```
src/arichds/
├── main.py            FastAPI app + lifespan (migrate → license → poller → serve)
├── config.py          ARICHDS_* settings; owns where data lives
├── constants.py       every timeout, OBIS code and cadence — no magic numbers
├── logging_config.py  credential redaction filter, attached to every handler
├── fe_static.py       locates the built SPA (env → frozen bundle → web/dist)
├── db/                models, engine/session, programmatic `alembic upgrade head`
├── migrations/        the single Alembic set (render_as_batch=True from 0001)
├── licensing/         Machine ID, Activation Codes, Limited Mode enforcement, feature
│                      entitlement (features.py) and the process-wide LicenseService holder
│                      for background code (current.py, M6b issue #22)
├── auth/              Role enum, bcrypt/PyJWT primitives, token service — no HTTP types
├── acquisition/       ConnectionParams, drivers, Poller, catalog, probe, endpoint locks,
│                      device status (the ADR 0004 state machine the tick feeds)
│   └── drivers/       MeterDriver ABC, Prometer100 (DLMS/TCP), factory
├── api/               health, auth, license, devices routers + the {success,data,error}
│                      envelope; deps.py holds the JWT guard dependencies + require_feature
├── capture/           billing capture PDF/xlsx (M6b, issue #22): path validation, the two
│                      renderers off one shared section module, the hardened write
└── vendor/gurux/      GX*.py copied verbatim from v1 — never edited, never linted
```

Anything under `acquisition/drivers/`, `vendor/gurux/`, or the probe and poller read paths
is DLMS work: read `.claude/skills/gurux-dlms/` first. The library is a camelCase C# port
with no upstream API docs, and that skill is where its lifecycle, scaler handling and
traps are written down. For *which* OBIS code to read rather than *how*, see
`docs/meter-notes/`.

## Development

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

# Serve on http://localhost:8000 (runs migrations first, serves web/dist if built)
.\.venv\Scripts\fastapi.exe dev src\arichds\main.py
```

The `[tool.fastapi]` entrypoint in `pyproject.toml` means plain `fastapi dev`
works too once the package is installed.

### Configuration

Every knob is an `ARICHDS_*` environment variable:

| Variable | Default | Meaning |
|---|---|---|
| `ARICHDS_DATA_DIR` | `./data` | Root of the database, license, logs, secret and daily backups. The installer sets `%ProgramData%\ARICHDS` |
| `ARICHDS_PORT` | `8000` | HTTP port |
| `ARICHDS_HOST` | `0.0.0.0` | Bind address (LAN-reachable by default) |
| `ARICHDS_LOG_LEVEL` | `INFO` | Root logger level |
| `ARICHDS_POLL_ENABLED` | `true` | Master switch for all background work — the Poller and every Scheduler job. Since M5c that includes two jobs that read no meter (the daily purge and the daily backup); it stays one switch by decision (issue #19) |
| `ARICHDS_FE_DIST` | *(unset)* | Override the SPA directory |
| `ARICHDS_TOKEN_EXPIRE_MINUTES` | `480` | Access Token lifetime (8 hours) |
| `ARICHDS_JWT_SECRET` | *(unset)* | Overrides the per-install key at `<data>\secret\jwt_secret.key` (ADR 0003) |
| `ARICHDS_FEATURES` | *(unset)* | Comma-separated feature keys requested; empty/unset requests every key in `constants.FEATURE_KEYS`. Enabled = this ∩ the licensed feature set (M6b, issue #22) |
| `ARICHDS_CAPTURE_ALLOWLIST` | *(unset)* | `os.pathsep`-separated absolute roots the `capture_dir` setting must resolve within; empty/unset means no root restriction (ADR 0010, M6b issue #22) |

## Quality gate

```powershell
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

## Talking to a real meter

`scripts/probe_meter.py` is a read-only operator diagnostic — it connects,
reads the Meter Serial (the one register the Poller's liveness tick reads,
ADR 0007) and then the instantaneous set, and disconnects, touching neither the
meter's settings nor the database. The app itself no longer reads that set;
the script keeps it because Output Parity against v1 is argued in those numbers:

```powershell
.\.venv\Scripts\python.exe scripts\probe_meter.py --host 203.0.113.10 --port 4059 --password ABCD0001
# add --show-scaler when checking output parity against v1
```

## Migrations

The app runs `alembic upgrade head` itself at startup, so there is no separate
migrate step. To author a new revision:

```powershell
.\.venv\Scripts\alembic.exe revision --autogenerate -m "add the thing"
```

`render_as_batch=True` is set from migration 0001 and must stay that way —
SQLite cannot `ALTER TABLE` to drop or alter a column.

## Packaging

See `packaging/build.ps1` and `../installer/README.md`.
