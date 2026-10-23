import pytest
from fakes import FakeVisaResource, fake_factory
from PySide6.QtCore import QTimer

from scope_gui import driver as driver_module
from scope_gui import settings
from scope_gui.driver import ScopeDriver
from scope_gui.errors import ScopeUnreachable
from scope_gui.models import ConnectionState
from scope_gui.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def reachable(monkeypatch):
    monkeypatch.setattr(driver_module, "tcp_precheck", lambda host, timeout=3.0: None)


def make_window(qtbot, fake=None, address="192.168.0.9"):
    factory = fake_factory(fake)
    window = MainWindow(address, driver_factory=lambda: ScopeDriver(resource_factory=factory))
    qtbot.addWidget(window)
    window.show()
    return window, factory.fake


def wait_state(qtbot, window, state, timeout=5000):
    qtbot.waitUntil(lambda: window._state is state, timeout=timeout)


def test_connect_shows_identity_and_saves_address(qtbot):
    window, fake = make_window(qtbot, address="192.168.0.9")
    window.connection_bar.address_edit.setText("192.168.0.9")
    window.connection_bar.button.click()
    wait_state(qtbot, window, ConnectionState.CONNECTED)
    bar = window.connection_bar
    assert bar.status_text.text() == "Connected"
    assert "LECROY WR610ZI" in bar.identity_label.text()
    assert "LCRY3201N55990" in bar.identity_label.text()
    assert "9.1.0" in bar.identity_label.text()
    assert bar.button.text() == "Disconnect"
    assert not bar.address_edit.isEnabled()
    assert fake.address == "TCPIP0::192.168.0.9::inst0::INSTR"
    assert settings.load_last_address() == "192.168.0.9"
    window.close()


def test_disconnect(qtbot):
    window, fake = make_window(qtbot)
    window.connection_bar.button.click()
    wait_state(qtbot, window, ConnectionState.CONNECTED)
    window.connection_bar.button.click()
    wait_state(qtbot, window, ConnectionState.DISCONNECTED)
    assert fake.closed
    assert window.connection_bar.button.text() == "Connect"
    assert window.connection_bar.identity_label.text() == ""
    window.close()


def test_unreachable_shows_error_and_stays_usable(qtbot, monkeypatch):
    def fail(host, timeout=3.0):
        raise ScopeUnreachable(f"Instrument not reachable at {host}")

    monkeypatch.setattr(driver_module, "tcp_precheck", fail)
    window, _ = make_window(qtbot, address="192.168.0.99")
    window.connection_bar.button.click()
    wait_state(qtbot, window, ConnectionState.ERROR)
    bar = window.connection_bar
    assert "not reachable at 192.168.0.99" in bar.status_text.text()
    assert bar.address_edit.isEnabled()
    assert bar.button.text() == "Connect"
    assert settings.load_last_address() == "192.168.0.9"  # not saved on failure
    window.close()


@pytest.mark.parametrize(
    "accept,final", [(False, ConnectionState.DISCONNECTED), (True, ConnectionState.CONNECTED)]
)
def test_unsupported_instrument_asks(qtbot, monkeypatch, accept, final):
    fake = FakeVisaResource()
    fake.set_reply("*IDN?", "*IDN KEYSIGHT,DSOX3024T,MY123,2.65")
    window, _ = make_window(qtbot, fake)
    asked = []
    monkeypatch.setattr(window, "ask_continue", lambda identity: asked.append(identity) or accept)
    window.connection_bar.button.click()
    qtbot.waitUntil(lambda: bool(asked), timeout=5000)
    wait_state(qtbot, window, final)
    assert asked and asked[0].manufacturer == "KEYSIGHT"
    window.close()


def test_window_responsive_while_connecting(qtbot, monkeypatch):
    import time

    def slow(host, timeout=3.0):
        time.sleep(1.0)

    monkeypatch.setattr(driver_module, "tcp_precheck", slow)
    window, _ = make_window(qtbot)
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(50)
    window.connection_bar.button.click()
    qtbot.waitUntil(lambda: len(ticks) >= 5, timeout=900)  # GUI thread keeps running
    assert window._state is ConnectionState.CONNECTING
    wait_state(qtbot, window, ConnectionState.CONNECTED)
    timer.stop()
    window.close()


def test_cancel_while_connecting(qtbot, monkeypatch):
    import time

    monkeypatch.setattr(driver_module, "tcp_precheck", lambda host, timeout=3.0: time.sleep(0.5))
    window, _ = make_window(qtbot)
    window.connection_bar.button.click()
    wait_state(qtbot, window, ConnectionState.CONNECTING)
    assert window.connection_bar.button.text() == "Cancel"
    window.connection_bar.button.click()
    wait_state(qtbot, window, ConnectionState.DISCONNECTED)
    window.close()
