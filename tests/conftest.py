import socket

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--scope-address",
        default="192.168.0.9",
        help="IP/hostname of the real scope used by hardware tests",
    )
    parser.addoption(
        "--live-seconds",
        type=int,
        default=30,
        help="duration of the hardware live read-only session (SC-005 asks for 600)",
    )


@pytest.fixture(scope="session")
def live_seconds(request):
    return request.config.getoption("--live-seconds")


@pytest.fixture(scope="session")
def scope_address(request):
    return request.config.getoption("--scope-address")


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Never touch the user's real QSettings (Windows registry) from tests."""
    from PySide6.QtCore import QSettings

    from scope_gui import settings

    path = str(tmp_path / "scope_gui_settings.ini")
    monkeypatch.setattr(settings, "_settings", lambda: QSettings(path, QSettings.Format.IniFormat))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def _reachable(host: str) -> bool:
    try:
        with socket.create_connection((host, 111), timeout=3):
            return True
    except OSError:
        return False


def pytest_collection_modifyitems(config, items):
    hardware = [item for item in items if "hardware" in item.keywords]
    if not hardware:
        return
    host = config.getoption("--scope-address")
    if not _reachable(host):
        skip = pytest.mark.skip(reason=f"scope not reachable at {host}:111")
        for item in hardware:
            item.add_marker(skip)
