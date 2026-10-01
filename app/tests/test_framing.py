"""Framing — WRAPPER or HDLC — is a property of the **install**, not the model
(``docs/issues/025``, site TC 2026-09-20).

A Prometer 100 behind a transparent serial-to-TCP converter speaks HDLC; the
same model with its own TCP stack speaks WRAPPER. The driver used to fix the
framing together with the model's column maps, so the site's operator could
only reach the meter by calling it a Premier 550 — whose maps then stored 5 of
its 25 Logger 1 columns and none of Logger 2: no voltage, no current.

Framing is therefore a field of the ``net`` transport, beside host and port
(the same reasoning ``ModelSpec`` records for serial-vs-TCP), and a driver
**declares** which framings it has been measured on — a flag turns on from a
meter, never from a datasheet (ADR 0011's rule, applied here).
"""

from __future__ import annotations

import pytest

from arichds.acquisition.connection_params import ConnectionParams, connection_params_from_transport
from arichds.acquisition.drivers import factory
from arichds.acquisition.drivers.factory import create_driver, supported_framings, supported_models
from arichds.acquisition.drivers.premier550 import Premier550Driver
from arichds.acquisition.drivers.prometer100 import Prometer100Driver

#: Captured at import, before any fixture runs: ``conftest.fake_meter`` is autouse
#: and swaps ``factory._registry`` for two fakes, which is right for every test
#: that might open a socket and wrong for these — they are *about* what the real
#: drivers declare, and none of them connects to anything.
_REAL_REGISTRY = factory._registry  # noqa: SLF001


@pytest.fixture(autouse=True)
def _real_registry(fake_meter: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the product's registry back, *after* the suite-wide fake installed its own."""
    monkeypatch.setattr(factory, "_registry", _REAL_REGISTRY)


def _flag(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


class TestConnectionParamsCarryTheFraming:
    def test_net_without_a_framing_is_exactly_what_it_was(self) -> None:
        conn = ConnectionParams.net("10.0.0.5", 4059)

        assert conn.framing is None
        assert conn.transport_args() == ["-h", "10.0.0.5", "-p", "4059"]

    def test_net_carries_a_framing(self) -> None:
        assert ConnectionParams.net("10.0.0.5", 4059, framing="hdlc").framing == "hdlc"

    def test_the_framing_never_changes_the_transport_endpoint(self) -> None:
        """The endpoint is the lock key (ADR 0006): two devices on one
        ``host:port`` must still queue behind one lock whatever they speak."""
        assert ConnectionParams.net("10.0.0.5", 4059, framing="hdlc").endpoint == "10.0.0.5:4059"

    def test_a_stored_transport_hands_its_framing_over(self) -> None:
        conn = connection_params_from_transport({"kind": "net", "host": "10.0.0.5", "port": 4059, "framing": "hdlc"})

        assert conn.framing == "hdlc"

    @pytest.mark.parametrize("stored", [{}, {"framing": None}, {"framing": ""}])
    def test_a_transport_stored_before_the_field_existed_means_the_drivers_default(self, stored: dict) -> None:
        conn = connection_params_from_transport({"kind": "net", "host": "10.0.0.5", "port": 4059, **stored})

        assert conn.framing is None

    def test_a_framing_is_normalised_to_lower_case(self) -> None:
        conn = connection_params_from_transport({"kind": "net", "host": "h", "port": 1, "framing": "HDLC"})

        assert conn.framing == "hdlc"


class TestADriverDeclaresTheFramingsItWasMeasuredOn:
    def test_prometer_100_offers_both_with_its_historic_default_first(self) -> None:
        assert supported_framings("prometer100") == ("wrapper", "hdlc")

    def test_every_other_model_offers_no_choice(self) -> None:
        """Nothing else has been measured on a second framing. An empty tuple,
        not a one-item one: there is nothing for the form to offer."""
        for model in supported_models():
            if model != "prometer100":
                assert supported_framings(model) == (), model

    def test_an_unknown_model_offers_nothing_rather_than_raising(self) -> None:
        assert supported_framings("no-such-model") == ()


class TestThePrometer100SpeaksWhatItIsTold:
    def test_no_framing_is_wrapper_exactly_as_before(self) -> None:
        driver = Prometer100Driver(ConnectionParams.net("10.0.0.5", 4059), password="pw")

        args = driver._protocol_args()  # noqa: SLF001

        assert _flag(args, "-i") == "WRAPPER"
        assert "-l" not in args

    def test_wrapper_named_explicitly_is_the_same_thing(self) -> None:
        default = Prometer100Driver(ConnectionParams.net("h", 1), password="pw")._protocol_args()  # noqa: SLF001
        named = Prometer100Driver(ConnectionParams.net("h", 1, framing="wrapper"), password="pw")._protocol_args()  # noqa: SLF001

        assert named == default

    def test_hdlc_uses_the_argument_list_the_site_meter_is_proven_to_answer(self) -> None:
        """Site TC's Prometer 100 associates with the Premier 550 driver's flags
        and with nothing else we have — so HDLC here is *that list*, flag for
        flag, not a fresh guess at what HDLC needs."""
        hdlc = Prometer100Driver(ConnectionParams.net("h", 1, framing="hdlc"), password="pw")._protocol_args()  # noqa: SLF001
        proven = Premier550Driver(ConnectionParams.net("h", 1), password="pw")._protocol_args()  # noqa: SLF001

        assert hdlc == proven
        assert _flag(hdlc, "-i") == "HDLC"

    def test_the_column_maps_do_not_depend_on_the_framing(self) -> None:
        """The whole point: a Prometer 100 over HDLC is still read as a Prometer 100."""
        hdlc = Prometer100Driver(ConnectionParams.net("h", 1, framing="hdlc"), password="pw")

        assert hdlc.LOAD_PROFILE_COLUMN_MAP is Prometer100Driver.LOAD_PROFILE_COLUMN_MAP
        assert hdlc.model_name == "prometer100"


class TestAFramingAModelWasNeverMeasuredOnIsRefused:
    def test_the_factory_refuses_it_by_name(self) -> None:
        with pytest.raises(ValueError, match="premier550.*wrapper"):
            create_driver("premier550", ConnectionParams.net("h", 1, framing="wrapper"), password="pw")

    def test_a_supported_framing_builds_a_driver(self) -> None:
        driver = create_driver("prometer100", ConnectionParams.net("h", 1, framing="hdlc"), password="pw")

        assert isinstance(driver, Prometer100Driver)

    def test_no_framing_builds_every_model_as_before(self) -> None:
        for model in supported_models():
            create_driver(model, ConnectionParams.net("h", 1), password="pw")
