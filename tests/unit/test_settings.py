import pytest
from PySide6.QtCore import QSettings

from scope_gui import settings


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


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    path = str(tmp_path / "settings.ini")
    monkeypatch.setattr(settings, "_settings", lambda: QSettings(path, QSettings.Format.IniFormat))


def test_last_address_default(temp_settings):
    assert settings.load_last_address() == "192.168.0.9"


def test_last_address_round_trip(temp_settings):
    settings.save_last_address(" 10.1.2.3 ")
    assert settings.load_last_address() == "10.1.2.3"


def test_log_dir_created(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = settings.log_dir()
    assert path == tmp_path / "scope_gui" / "logs"
    assert path.is_dir()
