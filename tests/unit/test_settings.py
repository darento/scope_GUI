import json
import logging

import pytest

from scope_gui import settings
from scope_gui.analysis import Edge, Kind, Level, MeasurementSpec


@pytest.mark.parametrize(
    "address,resource",
    [
        ("192.168.0.9", "TCPIP0::192.168.0.9::inst0::INSTR"),
        ("  scope-lab.local ", "TCPIP0::scope-lab.local::inst0::INSTR"),
        ("TCPIP0::10.0.0.5::inst0::INSTR", "TCPIP0::10.0.0.5::inst0::INSTR"),
    ],
)
def test_to_visa_resource(address, resource):
    assert settings.to_visa_resource(address) == resource


def test_to_visa_resource_empty():
    with pytest.raises(ValueError):
        settings.to_visa_resource("   ")


def test_host_of():
    assert settings.host_of("TCPIP0::192.168.0.9::inst0::INSTR") == "192.168.0.9"
    assert settings.host_of("192.168.0.9") == "192.168.0.9"


def test_last_address_default():
    assert settings.load_last_address() == "192.168.0.9"


def test_last_address_round_trip():
    settings.save_last_address(" 10.1.2.3 ")
    assert settings.load_last_address() == "10.1.2.3"


def test_log_dir_created(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = settings.log_dir()
    assert path == tmp_path / "scope_gui" / "logs"
    assert path.is_dir()


SPECS = [
    MeasurementSpec(Kind.DELTA_T, "C2", Level(0.2, True), "C3", Level(0.2, True)),
    MeasurementSpec(Kind.DELTA_T, "C2", Level(0.03), "C4", Level(-0.4, edge=Edge.FALLING)),
    MeasurementSpec(Kind.AMPLITUDE, "C2"),
]


def test_measurements_default_empty():
    assert settings.load_measurements() == []


def test_measurements_round_trip():
    settings.save_measurements(SPECS)
    assert settings.load_measurements() == SPECS
    stored = json.loads(settings._settings().value("analysis/measurements"))
    assert stored[0]["kind"] == "DELTA_T"


def test_invalid_measurements_skipped(caplog):
    entries = [SPECS[0].to_dict(), {"kind": "NOPE"}, {"source": "C1"}, SPECS[2].to_dict()]
    settings._settings().setValue("analysis/measurements", json.dumps(entries))
    with caplog.at_level(logging.WARNING):
        assert settings.load_measurements() == [SPECS[0], SPECS[2]]
    assert "skipping invalid measurement" in caplog.text


def test_unreadable_measurements_ignored():
    settings._settings().setValue("analysis/measurements", "not json")
    assert settings.load_measurements() == []
