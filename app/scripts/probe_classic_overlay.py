"""Lay a Classic capture over a PNG ARICHDS Meter itself wrote (ADR 0028, capture-style ticket 03).

A probe, not a test: it needs a real Microsoft Edge and the customer's reference file, which
stays out of the repository (real serial, group and readings). It boots a real ARICHDS server
in this process on a throw-away data directory, seeds the device and the eight closed periods
the reference pictures (WP081200's rows, as ARICHDS Meter's own ``billing.csv`` holds them), a
group of 212 devices whose Poller statuses give ``212 / 36 / 176``, sets the Capture Style to
Classic, renders through the real ``render_billing_png`` and writes, beside the reference:

* ``ours.png`` — what ARICHDS wrote;
* ``overlay.png`` — reference | ours | absolute-difference heat map, side by side;
* ``blend.png`` — the two at 50 %, the picture a person judges alignment from;
* a per-region table on stdout (mean difference and the share of pixels that differ by more
  than anti-aliasing would), plus the eight rows as the Classic endpoint formatted them next to
  the strings the reference shows.

Run from ``app/`` with the dev extras installed (``httpx`` is dev-only; Pillow is a runtime
dependency through fpdf2)::

    .venv\\Scripts\\python scripts\\probe_classic_overlay.py --reference "C:\\...\\capture_WP081200.png" --out "C:\\...\\overlay"

``--launch task`` (the default) triggers Edge exactly as the product does — through the
``ARICHDS Capture Browser`` scheduled task, which needs an administrator terminal.
``--launch direct`` starts ``msedge.exe`` from this process under the current user instead,
for a machine where the task is not registered or the shell is not elevated; the CDP drive
and everything after it are the product's own code either way.

Nothing here touches ``%ProgramData%\\ARICHDS``, a real meter, or the reference file (read only).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import uvicorn
from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import arichds_vendor  # noqa: E402 — the real issuer, imported the way tests/conftest.py does

ADMIN = {"username": "admin", "password": "probe-admin-password"}
SERIAL = "WP081200"
GROUP = "PWA Phase.2 Days1"
SAVE_PATH = r"C:\CEWE DATA Billing_"
LOCAL_OFFSET = timedelta(hours=7)

#: ARICHDS Meter's ``billing.csv`` rows for WP081200 (2026-09-22), the columns the Classic
#: image shows plus the demand columns to their right: (Time, Total, A, B, C, kW A, time A,
#: kW B, time B, kW C, time C). Times are meter-local ``M/D/YYYY HH:MM``.
ROWS = [
    (
        "2/1/2026 00:00",
        9667.7793,
        6062.6192,
        531.1983,
        3073.9618,
        75.4924,
        "1/10/2026 12:30",
        35.6349,
        "1/16/2026 18:30",
        74.6338,
        "1/16/2026 18:30",
    ),
    (
        "3/1/2026 00:00",
        18822.0049,
        12091.5330,
        1060.5276,
        5669.9443,
        78.0317,
        "2/28/2026 12:00",
        41.6311,
        "2/16/2026 18:45",
        79.5268,
        "2/16/2026 18:45",
    ),
    (
        "4/1/2026 00:00",
        30194.5989,
        19159.8494,
        1852.0632,
        9182.6863,
        78.7031,
        "3/21/2026 12:30",
        44.2263,
        "3/3/2026 18:45",
        79.8895,
        "3/2/2026 18:45",
    ),
    (
        "5/1/2026 00:00",
        41690.9467,
        25587.4656,
        2755.9259,
        13347.5552,
        76.9162,
        "4/26/2026 12:30",
        50.8630,
        "4/28/2026 19:00",
        67.2687,
        "4/28/2026 19:00",
    ),
    (
        "6/1/2026 00:00",
        51135.0910,
        30777.9971,
        3617.8949,
        16739.1990,
        86.2971,
        "5/17/2026 11:00",
        50.7701,
        "5/3/2026 19:00",
        81.8988,
        "5/6/2026 19:00",
    ),
    (
        "7/1/2026 00:00",
        61249.9400,
        36980.7465,
        4761.7415,
        19507.4520,
        88.0773,
        "6/14/2026 11:00",
        57.0340,
        "6/18/2026 19:15",
        78.5015,
        "6/18/2026 19:15",
    ),
    (
        "8/1/2026 00:00",
        70596.9325,
        42037.1525,
        5486.3236,
        23073.4564,
        81.5585,
        "7/4/2026 11:30",
        64.5151,
        "7/28/2026 19:15",
        73.6464,
        "7/2/2026 19:15",
    ),
    (
        "9/1/2026 00:00",
        80090.6412,
        47621.3174,
        6188.2991,
        26281.0247,
        84.5593,
        "8/22/2026 12:45",
        52.8063,
        "8/24/2026 19:00",
        80.8403,
        "8/24/2026 19:00",
    ),
]

#: The strings the reference image shows for those rows, left to right up to the window edge —
#: what the Classic endpoint must answer cell for cell.
EXPECTED_CELLS = [
    (
        "CEWE (WP081200)",
        "2/1/2026 00:00",
        "9667.7793",
        "6062.6192",
        "531.1983",
        "3073.9618",
        "75.4924",
        "1/10/2026 12:30",
        "35.6349",
    ),
    (
        "CEWE (WP081200)",
        "3/1/2026 00:00",
        "18822.0049",
        "12091.533",
        "1060.5276",
        "5669.9443",
        "78.0317",
        "2/28/2026 12:00",
        "41.6311",
    ),
    (
        "CEWE (WP081200)",
        "4/1/2026 00:00",
        "30194.5989",
        "19159.8494",
        "1852.0632",
        "9182.6863",
        "78.7031",
        "3/21/2026 12:30",
        "44.2263",
    ),
    (
        "CEWE (WP081200)",
        "5/1/2026 00:00",
        "41690.9467",
        "25587.4656",
        "2755.9259",
        "13347.5552",
        "76.9162",
        "4/26/2026 12:30",
        "50.863",
    ),
    (
        "CEWE (WP081200)",
        "6/1/2026 00:00",
        "51135.091",
        "30777.9971",
        "3617.8949",
        "16739.199",
        "86.2971",
        "5/17/2026 11:00",
        "50.7701",
    ),
    (
        "CEWE (WP081200)",
        "7/1/2026 00:00",
        "61249.94",
        "36980.7465",
        "4761.7415",
        "19507.452",
        "88.0773",
        "6/14/2026 11:00",
        "57.034",
    ),
    (
        "CEWE (WP081200)",
        "8/1/2026 00:00",
        "70596.9325",
        "42037.1525",
        "5486.3236",
        "23073.4564",
        "81.5585",
        "7/4/2026 11:30",
        "64.5151",
    ),
    (
        "CEWE (WP081200)",
        "9/1/2026 00:00",
        "80090.6412",
        "47621.3174",
        "6188.2991",
        "26281.0247",
        "84.5593",
        "8/22/2026 12:45",
        "52.8063",
    ),
]
CELL_KEYS = (
    "name",
    "time",
    "total_kwh_total",
    "total_kwh_rate_a",
    "total_kwh_rate_b",
    "total_kwh_rate_c",
    "prev_kw_demand_rate_a",
    "time_of_kw_demand_a",
    "prev_kw_demand_rate_b",
)

#: Regions of the 1280×709 frame, as (x0, y0, x1, y1) inclusive of x0/y0 and exclusive of x1/y1.
REGIONS = {
    "toolbar": (0, 0, 520, 55),
    "Save Path box": (20, 60, 1260, 120),
    "Data Billing group frame": (20, 130, 712, 287),
    "Group row": (24, 148, 230, 174),
    "Statistics Summary": (27, 180, 705, 218),
    "tabs": (22, 222, 120, 248),
    "Device row + Read Billing": (23, 250, 330, 280),
    "Auto Read Schedule": (717, 130, 1260, 287),
    "Data Table header": (22, 349, 1242, 374),
    "column Name": (23, 374, 223, 535),
    "column Time": (223, 374, 373, 535),
    "column Total kWh Total": (373, 374, 493, 535),
    "column Rate A": (493, 374, 613, 535),
    "column Rate B": (613, 374, 733, 535),
    "column Rate C": (733, 374, 853, 535),
    "column Prev kW Demand A": (853, 374, 993, 535),
    "column Time of kW Demand A": (993, 374, 1133, 535),
    "column Prev kW Demand B (cut)": (1133, 374, 1242, 535),
    "table body below rows": (23, 535, 1242, 658),
    "vertical scrollbar": (1242, 349, 1259, 676),
    "horizontal scrollbar": (22, 658, 1242, 676),
    "status line": (20, 680, 300, 705),
}


def local_to_utc(text: str) -> datetime:
    return datetime.strptime(text, "%m/%d/%Y %H:%M").replace(tzinfo=UTC) - LOCAL_OFFSET


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until_reachable(client: httpx.Client, deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            if client.get("/api/health").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise TimeoutError("the in-process server never became reachable")


def seed(device_status_counts: tuple[int, int]) -> int:
    """Insert WP081200 with its eight closed periods and the rest of its group. Returns the device id."""
    from arichds.db.app_settings import CAPTURE_DIR_KEY, CAPTURE_STYLE_KEY, set_setting
    from arichds.db.models import BillingReading, Device
    from arichds.db.session import session_scope

    online, offline = device_status_counts

    def device(name: str, status: str, serial: str | None = None) -> Device:
        return Device(
            name=name,
            brand="cewe",
            model="prometer100",
            site_name="PWA",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="",
            meter_serial=serial,
            group_name=GROUP,
            enabled=True,
            status=status,
        )

    with session_scope() as session:
        main = device(SERIAL, "online", SERIAL)
        session.add(main)
        session.flush()
        for n in range(online - 1):
            session.add(device(f"online-{n + 1}", "online"))
        for n in range(offline):
            session.add(device(f"offline-{n + 1}", "offline"))
        for time_text, total, a, b, c, kw_a, t_a, kw_b, t_b, kw_c, t_c in ROWS:
            bill_date = local_to_utc(time_text)
            session.add(
                BillingReading(
                    device_id=main.id,
                    bill_date=bill_date,
                    sequence=0,
                    read_at=bill_date,
                    record_status=None,
                    source="dlms",
                    meter_serial=SERIAL,
                    import_active_kwh_total=total,
                    import_active_kwh_rate_a=a,
                    import_active_kwh_rate_b=b,
                    import_active_kwh_rate_c=c,
                    max_demand_import_active_kw_rate_a=kw_a,
                    max_demand_import_active_time_rate_a=local_to_utc(t_a),
                    max_demand_import_active_kw_rate_b=kw_b,
                    max_demand_import_active_time_rate_b=local_to_utc(t_b),
                    max_demand_import_active_kw_rate_c=kw_c,
                    max_demand_import_active_time_rate_c=local_to_utc(t_c),
                )
            )
        set_setting(session, CAPTURE_STYLE_KEY, "classic")
        set_setting(session, CAPTURE_DIR_KEY, SAVE_PATH)
        return main.id


def launch_edge_directly() -> Callable[[], None]:
    """Replace the scheduled-task trigger with a direct ``msedge.exe`` launch under this user —
    the same flags the task carries, the same reused profile directory, so the CDP drive that
    follows is untouched."""
    import arichds.capture.screenshot as screenshot_module
    from arichds.capture.task import EDGE_TASK_ARGUMENTS
    from arichds.config import get_settings

    edge = screenshot_module.resolve_edge_path()
    if edge is None:
        raise SystemExit("Microsoft Edge was not found on this machine.")
    processes: list[subprocess.Popen[bytes]] = []

    def trigger() -> None:
        profile_dir = get_settings().tmp_dir
        (profile_dir / "DevToolsActivePort").unlink(missing_ok=True)
        args = [str(edge), *EDGE_TASK_ARGUMENTS[:-1], f"--user-data-dir={profile_dir}", EDGE_TASK_ARGUMENTS[-1]]
        processes.append(subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    def end() -> None:
        while processes:
            process = processes.pop()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()

    # `_end_capture_task` is looked up on the module at cleanup time, so patching it takes; the
    # trigger is a *default argument* of `_run_capture`, bound at import, so it is passed in
    # explicitly by the caller instead (see `main`).
    screenshot_module._end_capture_task = end
    return trigger


def heat_map(difference: Image.Image) -> Image.Image:
    """Grey → black-through-red-to-yellow, so a 1px misalignment reads as a red edge."""
    grey = difference.convert("L")
    red = grey.point(lambda v: min(255, v * 4))
    green = grey.point(lambda v: max(0, min(255, (v - 64) * 4)))
    return Image.merge("RGB", (red, green, Image.new("L", grey.size, 0)))


def region_report(reference: Image.Image, ours: Image.Image) -> None:
    difference = ImageChops.difference(reference, ours).convert("L")
    print(f"\n{'region':34s} {'mean diff':>9s} {'pixels > 40':>12s}")
    for name, (x0, y0, x1, y1) in REGIONS.items():
        crop = difference.crop((x0, y0, x1, y1))
        histogram = crop.histogram()
        total = sum(histogram)
        over = sum(histogram[41:])
        mean = sum(i * n for i, n in enumerate(histogram)) / total
        print(f"{name:34s} {mean:9.2f} {100 * over / total:11.1f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", required=True, type=Path, help="the PNG ARICHDS Meter itself wrote")
    parser.add_argument("--out", required=True, type=Path, help="where ours.png / overlay.png / blend.png go")
    parser.add_argument("--launch", choices=("task", "direct"), default="task")
    args = parser.parse_args()

    reference = Image.open(args.reference).convert("RGB")
    if reference.size != (1280, 709):
        raise SystemExit(f"the reference is {reference.size}, not 1280x709 — not a PNG ARICHDS Meter wrote")
    args.out.mkdir(parents=True, exist_ok=True)

    data_dir = Path(tempfile.mkdtemp(prefix="arichds-classic-overlay-"))
    port = free_port()
    os.environ["ARICHDS_DATA_DIR"] = str(data_dir)
    os.environ["ARICHDS_PORT"] = str(port)
    os.environ["ARICHDS_POLL_ENABLED"] = "false"

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

    import arichds.licensing.service as licensing_service
    from arichds.config import get_settings
    from arichds.licensing import activation_code as ac

    get_settings.cache_clear()
    machine_id = "e" * 64
    licensing_service.machine_id = lambda: machine_id
    private_key = Ed25519PrivateKey.generate()  # throw-away — never the vendor key
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    ac.load_public_key_pem = lambda: private_key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    )

    trigger = launch_edge_directly() if args.launch == "direct" else None

    from arichds.main import create_app

    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
            wait_until_reachable(client, time.monotonic() + 20)
            assert client.post("/api/auth/setup", json=ADMIN).status_code == 201
            token = client.post("/api/auth/login", json=ADMIN).json()["data"]["access_token"]
            client.headers["Authorization"] = f"Bearer {token}"
            code = arichds_vendor.sign_payload(
                private_pem, arichds_vendor.build_payload(customer="Overlay Probe", machine_id=machine_id)
            )
            activated = client.post("/api/license/activate", json={"code": code})
            assert activated.status_code == 200 and activated.json()["success"], activated.text

            device_id = seed((176, 36))  # 212 in the group, 36 Offline → 212 / 36 / 176

            view = client.get(f"/api/billing/capture-classic/{device_id}").json()["data"]
            print(f"statistics: {view['statistics']}   save_path: {view['save_path']}   group: {view['group_name']}")
            mismatches = 0
            for expected, row in zip(EXPECTED_CELLS, view["rows"], strict=True):
                got = tuple(row[key] for key in CELL_KEYS)
                flag = "" if got == expected else "   <-- differs"
                mismatches += got != expected
                print(f"  {' | '.join(got)}{flag}")
            print(f"rows: {len(view['rows'])}, cells differing from the reference: {mismatches} rows")

        from sqlalchemy import select

        from arichds.capture.screenshot import _run_capture_with_hard_deadline, render_billing_png
        from arichds.capture.service import png_source_rows
        from arichds.db.models import BillingReading
        from arichds.db.session import session_scope

        with session_scope() as session:
            anchor = session.scalars(
                select(BillingReading)
                .where(BillingReading.device_id == device_id)
                .order_by(BillingReading.bill_date.desc(), BillingReading.sequence.asc())
                .limit(1)
            ).first()
            assert anchor is not None
            rows = png_source_rows(session, anchor)
            started = time.monotonic()
            if trigger is None:
                png = render_billing_png(rows, SERIAL)
            else:
                png = asyncio.run(_run_capture_with_hard_deadline(rows, SERIAL, trigger_browser=trigger))
            print(f"\nClassic capture: {len(png)} bytes in {time.monotonic() - started:.1f}s")
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    ours_path = args.out / "ours.png"
    ours_path.write_bytes(png)
    ours = Image.open(ours_path).convert("RGB")
    print(f"ours: {ours.size}  reference: {reference.size}")
    if ours.size != reference.size:
        raise SystemExit("sizes differ — nothing to overlay")

    difference = ImageChops.difference(reference, ours)
    overlay = Image.new("RGB", (1280 * 3, 709), "white")
    overlay.paste(reference, (0, 0))
    overlay.paste(ours, (1280, 0))
    overlay.paste(heat_map(difference), (2560, 0))
    overlay.save(args.out / "overlay.png")
    Image.blend(reference, ours, 0.5).save(args.out / "blend.png")
    region_report(reference, ours)
    print(f"\nwritten: {ours_path}, {args.out / 'overlay.png'}, {args.out / 'blend.png'}")


if __name__ == "__main__":
    main()
