"""``ConnectionParams`` — the single place that branches on transport (issue #9).

Two things are pinned here:

* The **serial** variant, added by issue #9: ``transport_args()`` emits the
  ``-S`` argv fragment exactly as the vendored ``GXSettings.py:224-244``
  parser expects, and ``endpoint`` is the bare COM port name (CONTEXT.md).
* **TCP behaviour is unchanged** — pinned because it is the regression risk
  of adding the branch.

The lock-key convergence between this module and ``Device.transport_endpoint``
is asserted end to end in ``test_poller.py`` (``TestTheLockKeyIsOneString``),
not here: this file is about ``ConnectionParams`` in isolation.
"""

from __future__ import annotations

import pytest

from arichds.acquisition.connection_params import ConnectionParams, ConnectionType, connection_params_from_transport


class TestNetIsUnchanged:
    """Pinned as a regression guard for the serial branch added beside it."""

    def test_transport_args(self) -> None:
        assert ConnectionParams.net("127.0.0.1", 4059).transport_args() == ["-h", "127.0.0.1", "-p", "4059"]

    def test_endpoint(self) -> None:
        assert ConnectionParams.net("127.0.0.1", 4059).endpoint == "127.0.0.1:4059"

    def test_repr_carries_no_secret_and_names_the_kind(self) -> None:
        assert repr(ConnectionParams.net("127.0.0.1", 4059)) == "ConnectionParams(net 127.0.0.1:4059)"


class TestSerial:
    def test_transport_args_at_the_smw110w4_field_defaults(self) -> None:
        """19200 8N1 — docs/meter-notes/smw110w4-scan.md."""
        conn = ConnectionParams.serial("COM4", baud_rate=19200, data_bits=8, parity="None", stop_bits=1)
        assert conn.transport_args() == ["-S", "COM4:19200:8None1"]

    def test_transport_args_with_a_non_default_parity_and_stop_bits(self) -> None:
        """Even parity, 2 stop bits — GXSettings.py:224-244 slices by position,
        not by a fixed width, so a longer parity name must still parse."""
        conn = ConnectionParams.serial("COM7", baud_rate=9600, data_bits=7, parity="Even", stop_bits=2)
        assert conn.transport_args() == ["-S", "COM7:9600:7Even2"]

    def test_the_dash_s_fragment_matches_what_gxsettings_parses(self) -> None:
        """Reproduce ``GXSettings.py``'s own slicing so the format is verified
        against the parser, not merely against our own formatting."""
        conn = ConnectionParams.serial("COM4", baud_rate=19200, data_bits=8, parity="None", stop_bits=1)
        _flag, value = conn.transport_args()
        port, baud, fmt = value.split(":")
        assert port == "COM4"
        assert baud == "19200"
        data_bits_char = fmt[0:1]
        parity_name = fmt[1 : len(fmt) - 1]
        stop_bits_char = fmt[len(fmt) - 1 :]
        assert data_bits_char == "8"
        assert parity_name.upper() == "NONE"
        assert int(stop_bits_char) - 1 == 0  # StopBits.ONE

    def test_endpoint_is_the_bare_com_port_not_a_human_label(self) -> None:
        """CONTEXT.md — a COM port name for serial, never ``"COM4:19200"``."""
        conn = ConnectionParams.serial("COM4", baud_rate=19200, data_bits=8, parity="None", stop_bits=1)
        assert conn.endpoint == "COM4"

    def test_repr_carries_no_secret_and_names_the_kind(self) -> None:
        conn = ConnectionParams.serial("COM4")
        assert repr(conn) == "ConnectionParams(serial COM4)"

    def test_connection_type_is_serial(self) -> None:
        assert ConnectionParams.serial("COM4").connection_type is ConnectionType.SERIAL


class TestConnectionParamsFromTransport:
    """The one function that turns a stored/submitted dict into a connection."""

    def test_net(self) -> None:
        conn = connection_params_from_transport({"kind": "net", "host": "192.168.1.31", "port": 4059})
        assert conn.connection_type is ConnectionType.NET
        assert conn.endpoint == "192.168.1.31:4059"

    def test_serial(self) -> None:
        conn = connection_params_from_transport(
            {
                "kind": "serial",
                "serial_port": "COM4",
                "baud_rate": 19200,
                "data_bits": 8,
                "parity": "None",
                "stop_bits": 1,
            }
        )
        assert conn.connection_type is ConnectionType.SERIAL
        assert conn.endpoint == "COM4"
        assert conn.transport_args() == ["-S", "COM4:19200:8None1"]

    def test_missing_host_raises(self) -> None:
        with pytest.raises(ValueError, match="No usable"):
            connection_params_from_transport({"kind": "net", "port": 4059})

    def test_missing_port_raises(self) -> None:
        with pytest.raises(ValueError, match="No usable"):
            connection_params_from_transport({"kind": "net", "host": "192.168.1.31"})

    def test_missing_serial_port_raises(self) -> None:
        with pytest.raises(ValueError, match="No usable"):
            connection_params_from_transport({"kind": "serial", "baud_rate": 19200})

    def test_an_empty_mapping_raises(self) -> None:
        with pytest.raises(ValueError, match="No usable"):
            connection_params_from_transport({})
