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


@pytest.fixture
def running_bench(qtbot, monkeypatch):
    """``running_bench(mode="AUTO", rate_hz=500.0, triggers=True, scene=None) -> (window,
    scope)``: a connected window on a synthetic scope that runs like the WR610Zi (003)."""
    from synthetic_scope import Scene, SyntheticScope, synthetic_factory

    from scope_gui import driver as driver_module
    from scope_gui.driver import ScopeDriver
    from scope_gui.models import ConnectionState
    from scope_gui.ui.main_window import MainWindow

    monkeypatch.setattr(driver_module, "tcp_precheck", lambda host, timeout=3.0: None)
    windows = []

    def open_bench(mode="AUTO", rate_hz=500.0, triggers=True, scene=None):
        scene = scene or Scene(points=2000)
        scope = SyntheticScope(scene, rate_hz, 1, trigger_mode=mode, triggers=triggers)
        factory = synthetic_factory(scope)
        window = MainWindow("synthetic", driver_factory=lambda: ScopeDriver(factory))
        windows.append(window)
        qtbot.addWidget(window)
        window.show()
        window.connection_bar.button.click()
        qtbot.waitUntil(lambda: window._state is ConnectionState.CONNECTED, timeout=5000)
        return window, scope

    yield open_bench
    for window in windows:
        window.close()
