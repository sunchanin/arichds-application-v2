"""Acceptance probe for ADR 0027 — a real two-Logger backfill, merged into a real MariaDB.

**Read-only against the meter.** ``fake_meter`` is autouse in the suite, so no
automated test can prove the one thing ADR 0027's cap rests on: that while the
load-profile walk reads Logger 1 to the present and Logger 2 follows a chunk per
visit, the Database Destination never sends a Logger 1 row ahead of a Logger 2
that is still arriving. This drives the shipped read path and the shipped sync,
alternately, the way the scheduler does, and checks two things after every
round:

* the **hold** — the destination's newest row is never newer than Logger 2's
  own frontier while Logger 2 is still arriving;
* the **merge** — once both Loggers are caught up, the destination holds
  exactly the rows :func:`merged_rows_select` produces, and a Logger-2-only
  column is NULL at the destination only where the merge itself says NULL.

Runs against a throw-away data directory (``ARICHDS_DATA_DIR``), never the
installed one, and drops/recreates ARICHDS's own two tables in the named
destination database.

Usage (from ``app/``; the meter password is read from the environment, never
from the command line)::

    set ARICHDS_PROBE_METER_PASSWORD=...
    .venv\\Scripts\\python.exe scripts\\probe_dbdest_merge_backfill.py ^
        --host 203.170.151.152 --port 4059 --model prometer100 ^
        --mysql mysql+pymysql://root:@127.0.0.1:3306/arichds_dest --rounds 40
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=4059)
    parser.add_argument("--model", default="prometer100")
    parser.add_argument("--framing", choices=("wrapper", "hdlc"), default=None)
    parser.add_argument("--mysql", required=True, help="SQLAlchemy URL of the destination database")
    parser.add_argument("--rounds", type=int, default=40, help="read+sync rounds before giving up")
    parser.add_argument("--column", default="volt_l1_l2", help="a column only Logger 2 captures on this model")
    args = parser.parse_args()

    password = os.environ.get("ARICHDS_PROBE_METER_PASSWORD", "")
    if not password:
        print("set ARICHDS_PROBE_METER_PASSWORD first")
        return 2

    data_dir = Path(tempfile.mkdtemp(prefix="arichds-merge-probe-"))
    os.environ["ARICHDS_DATA_DIR"] = str(data_dir)
    os.environ["ARICHDS_POLL_ENABLED"] = "false"
    print(f"[i] throw-away data dir: {data_dir}")

    import sqlalchemy as sa

    from arichds.acquisition.load_profile import read_and_store_load_profile
    from arichds.config import get_settings
    from arichds.constants import RETENTION_DAYS
    from arichds.dataout import sync
    from arichds.dataout.destination import DestinationConfig, create_destination_engine
    from arichds.dataout.schema import BILLING_TABLE, LOAD_PROFILE_TABLE
    from arichds.dataout.status import last_sync
    from arichds.db import session as db_session
    from arichds.db.app_settings import (
        DB_DEST_DATABASE_KEY,
        DB_DEST_HOST_KEY,
        DB_DEST_PASSWORD_KEY,
        DB_DEST_PORT_KEY,
        DB_DEST_USER_KEY,
        set_setting,
    )
    from arichds.db.load_profile_query import merged_rows_select
    from arichds.db.migrate import upgrade_to_head
    from arichds.db.models import Device, LoadProfileReading
    from arichds.db.session import session_scope
    from arichds.licensing.current import set_current_license_service
    from arichds.licensing.service import LicenseState

    class _EveryFeature:
        """A licence that gates nothing — the probe is about the sync, not the sale."""

        def current_state(self) -> LicenseState:
            return LicenseState(state="active", reason=None, features=None)

    url = sa.make_url(args.mysql)
    config = DestinationConfig(
        host=url.host or "127.0.0.1",
        port=url.port or 3306,
        database=url.database or "",
        user=url.username or "",
        password=url.password or "",
    )

    upgrade_to_head(get_settings().db_url)
    db_session.init_engine()
    set_current_license_service(_EveryFeature())

    transport = {"kind": "net", "host": args.host, "port": args.port}
    if args.framing:
        transport["framing"] = args.framing
    with session_scope() as session:
        set_setting(session, DB_DEST_HOST_KEY, config.host)
        set_setting(session, DB_DEST_PORT_KEY, str(config.port))
        set_setting(session, DB_DEST_DATABASE_KEY, config.database)
        set_setting(session, DB_DEST_USER_KEY, config.user)
        set_setting(session, DB_DEST_PASSWORD_KEY, config.password)
        device = Device(
            name="merge probe",
            brand="cewe",
            model=args.model,
            meter_serial="PROBE-MERGE",
            site_name="probe",
            transport=transport,
            password=password,
        )
        session.add(device)
        session.flush()
        device_id = device.id

    engine = create_destination_engine(config)
    with engine.begin() as connection:
        for table in (LOAD_PROFILE_TABLE, BILLING_TABLE):
            connection.execute(sa.text(f"DROP TABLE IF EXISTS {table.name}"))

    lp = LoadProfileReading.__table__

    def frontier(logger_id: int) -> tuple[int, datetime | None]:
        with session_scope() as session:
            count, newest = session.execute(
                sa.select(sa.func.count(), sa.func.max(lp.c.read_at)).where(
                    lp.c.device_id == device_id, lp.c.logger_id == logger_id
                )
            ).one()
        return int(count), newest.replace(tzinfo=UTC) if newest is not None and newest.tzinfo is None else newest

    def destination() -> tuple[int, datetime | None]:
        with engine.connect() as connection:
            exists = connection.execute(
                sa.text(
                    "SELECT COUNT(*) FROM information_schema.tables WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
                ),
                {"t": LOAD_PROFILE_TABLE.name},
            ).scalar_one()
            if not exists:
                return 0, None
            count, newest_local = connection.execute(
                sa.text(f"SELECT COUNT(*), MAX(read_at) FROM {LOAD_PROFILE_TABLE.name}")
            ).one()
        return int(count), sync._from_local(newest_local) if newest_local is not None else None  # noqa: SLF001

    hold_broken = 0
    caught_up = False
    previous: tuple[int, int, int] | None = None
    print(
        f"{'round':>5} {'stored':>7} {'L1 rows':>8} {'L2 rows':>8} {'L1 max':>17} {'L2 max':>17} {'dest rows':>9} {'dest max':>17}  hold"
    )
    for round_no in range(1, args.rounds + 1):
        started = time.monotonic()
        result = read_and_store_load_profile(device_id)
        sync.database_destination_cycle()
        status = last_sync()
        if status is None or status.error is not None:
            print(f"[x] sync failed: {status.error if status else 'no status'}")
            return 1

        l1_rows, l1_max = frontier(1)
        l2_rows, l2_max = frontier(2)
        dest_rows, dest_max = destination()
        # The hold: while Logger 2 is behind Logger 1, nothing newer than Logger
        # 2's frontier may have left. (Logger 2 absent: the 24 h rule applies and
        # the destination is simply a day behind — also never past a frontier.)
        ok = dest_max is None or l2_max is None or dest_max <= l2_max or (l1_max is not None and l2_max >= l1_max)
        hold_broken += 0 if ok else 1

        def fmt(value: datetime | None) -> str:
            return value.strftime("%m-%d %H:%M") if value is not None else "-"

        print(
            f"{round_no:>5} {result.stored:>7} {l1_rows:>8} {l2_rows:>8} {fmt(l1_max):>17} {fmt(l2_max):>17} "
            f"{dest_rows:>9} {fmt(dest_max):>17}  {'ok' if ok else 'BROKEN'}"
            f"   ({time.monotonic() - started:.0f}s{', ' + result.error if result.error else ''})"
        )
        sys.stdout.flush()
        # `stored` counts overwrites too, and every visit re-reads the newest
        # interval — so "nothing new" is the row counts standing still, not 0.
        settled = (l1_rows, l2_rows, dest_rows) == previous
        previous = (l1_rows, l2_rows, dest_rows)
        if l1_max is not None and l2_max is not None and l2_max >= l1_max and settled:
            caught_up = True
            break

    # The merge, judged against the one query the page and the CSV are built on —
    # inside the Mirror Window only. The destination purges past RETENTION_DAYS
    # on every cycle while our own retention runs daily (ADR 0020: "the same
    # length but not the same instant"), so during a run the oldest rows age out
    # there first. The first real run of this probe called that a FAIL: one row,
    # 2026-06-23 12:15, eight minutes behind the cutoff. Both sides are bounded
    # by a cutoff taken *now*, later than any purge that has already run.
    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    with session_scope() as session:
        truth = (
            session.execute(
                merged_rows_select(device_id).where(
                    LoadProfileReading.read_at <= (frontier(2)[1] or datetime.now(UTC)),
                    LoadProfileReading.read_at >= cutoff,
                )
            )
            .mappings()
            .all()
        )
    truth_null = sum(1 for row in truth if row[args.column] is None)
    with engine.connect() as connection:
        dest_total, dest_null = connection.execute(
            sa.text(
                f"SELECT COUNT(*), SUM({args.column} IS NULL) FROM {LOAD_PROFILE_TABLE.name} WHERE read_at >= :cutoff"
            ),
            {"cutoff": sync._to_local(cutoff)},  # noqa: SLF001
        ).one()
    engine.dispose()

    print()
    print(f"[i] caught up within {args.rounds} rounds: {caught_up}")
    print(f"[i] hold broken in {hold_broken} round(s)")
    print(
        f"[i] merged rows in our store (up to Logger 2's frontier): {len(truth)}, of which {args.column} NULL: {truth_null}"
    )
    print(
        f"[i] rows at the destination:                              {int(dest_total)}, of which {args.column} NULL: {int(dest_null or 0)}"
    )
    verdict = hold_broken == 0 and int(dest_total) == len(truth) and int(dest_null or 0) == truth_null
    print("[+] PASS" if verdict else "[x] FAIL")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
