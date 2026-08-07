"""The SMW110W4 driver — without a meter (issue #9, milestone M4a).

Mirrors ``test_probe.py::TestDlmsSerialRead``, which does exactly this for
Prometer100: assert facts about the class and its argv construction with no
socket or COM port opened. Nothing here touches a real meter — see the
delegation prompt's "you must NOT attempt a real meter read".
"""

from __future__ import annotations

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.smw110 import Smw110Driver


class TestMeterSerialObis:
    """The Meter Serial register is a class-attribute override, never a
    branch (Decision 10) — ``Smw110Driver`` overrides the base class's
    DLMS-standard default with the Mitsubishi manufacturer register.
    """

    def test_it_overrides_the_mitsubishi_register(self) -> None:
        assert Smw110Driver.METER_SERIAL_OBIS == ("1.0.199.128.134.255", 2)

    def test_it_is_declared_directly_on_the_class_not_merely_inherited(self) -> None:
        """The override, not a coincidence.

        ``isinstance(..., tuple)`` alone would pass identically if the
        override were deleted, since the base class's own default is also a
        tuple — it would not catch the regression this attribute exists to
        prevent. Checking ``__dict__`` is what actually distinguishes "this
        class overrides it" from "this class inherited something the same
        shape" (A capability flag, not an if/elif model chain — CLAUDE.md).
        """
        assert "METER_SERIAL_OBIS" in Smw110Driver.__dict__

    def test_the_driver_never_asks_for_the_standard_placeholder_register(self) -> None:
        """The standard `0.0.96.1.0.255` answers the factory placeholder
        `99999999` on this model — a future edit must not silently fall back
        to it (docs/meter-notes/smw110w4-scan.md)."""
        assert Smw110Driver.METER_SERIAL_OBIS[0] != "0.0.96.1.0.255"


class TestProtocolArgs:
    """The field-proven GXSettings argv, for both transports."""

    def driver(self, conn: ConnectionParams) -> Smw110Driver:
        return Smw110Driver(conn, password="00000000000000000003")

    def test_serial_build_args(self) -> None:
        conn = ConnectionParams.serial("COM4", baud_rate=19200, data_bits=8, parity="None", stop_bits=1)
        args = self.driver(conn)._build_args()

        assert args == [
            "smw110_driver.py",
            "-S", "COM4:19200:8None1",
            "-i", "HDLC",
            "-r", "ln",
            "-c", "6",
            "-s", "1",
            "-l", "0",
            "-a", "Low",
            "-P", "00000000000000000003",
            "-t", "Error",
        ]  # fmt: skip

    def test_tcp_build_args(self) -> None:
        conn = ConnectionParams.net("192.168.1.31", 4059)
        args = self.driver(conn)._build_args()

        assert args == [
            "smw110_driver.py",
            "-h", "192.168.1.31",
            "-p", "4059",
            "-i", "HDLC",
            "-r", "ln",
            "-c", "6",
            "-s", "1",
            "-l", "0",
            "-a", "Low",
            "-P", "00000000000000000003",
            "-t", "Error",
        ]  # fmt: skip

    def test_the_transport_fragment_comes_first(self) -> None:
        """The script name, then transport, then protocol flags — never mixed."""
        conn = ConnectionParams.serial("COM4")
        args = self.driver(conn)._build_args()
        assert args[1] == "-S"

    def test_l_follows_s(self) -> None:
        """The one flag it is easy to miss (probe_smw110_serial.py:241-242) —
        GXSettings combines the logical address using whatever `-s` already set,
        so `-l` must come after it."""
        conn = ConnectionParams.net("192.168.1.31", 4059)
        args = self.driver(conn)._build_args()
        s_index = args.index("-s")
        l_index = args.index("-l")
        assert l_index == s_index + 2

    def test_client_address_is_6_not_v1s_5(self) -> None:
        conn = ConnectionParams.net("192.168.1.31", 4059)
        args = self.driver(conn)._build_args()
        c_index = args.index("-c")
        assert args[c_index + 1] == "6"

    def test_read_timeout_is_60_seconds(self) -> None:
        conn = ConnectionParams.net("192.168.1.31", 4059)
        assert self.driver(conn)._read_timeout_ms() == 60_000


class TestIdentity:
    def test_model_name_is_the_locked_catalog_key(self) -> None:
        driver = Smw110Driver(ConnectionParams.net("192.168.1.31", 4059), password="x")
        assert driver.model_name == "smw110"

    def test_endpoint_matches_the_connection(self) -> None:
        driver = Smw110Driver(ConnectionParams.serial("COM4"), password="x")
        assert driver.endpoint == "COM4"
