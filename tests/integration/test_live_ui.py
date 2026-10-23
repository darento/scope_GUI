"""Live view end-to-end in the main window, with the worker thread and the fake instrument."""

import pytest
from fakes import FakeVisaResource, fake_factory

from scope_gui import driver as driver_module
from scope_gui.driver import ScopeDriver, is_allowed
from scope_gui.models import CHANNEL_COLORS, ConnectionState
from scope_gui.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def reachable(monkeypatch):
    monkeypatch.setattr(driver_module, "tcp_precheck", lambda host, timeout=3.0: None)


@pytest.fixture
def connected(qtbot):
    fake = FakeVisaResource()
    factory = fake_factory(fake)
    window = MainWindow("192.168.0.9", driver_factory=lambda: ScopeDriver(resource_factory=factory))
    qtbot.addWidget(window)
    window.show()
    window.connection_bar.button.click()
    qtbot.waitUntil(lambda: window._state is ConnectionState.CONNECTED, timeout=5000)
    qtbot.waitUntil(lambda: window.scope_plot.is_curve_visible("C1"), timeout=5000)
    yield window, fake, qtbot
    window.close()


def test_enabled_channels_plotted_in_scope_colours(connected):
    window, fake, qtbot = connected
    plot = window.scope_plot
    assert [ch for ch in ("C1", "C2", "C3", "C4") if plot.is_curve_visible(ch)] == [
        "C1",
        "C3",
        "C4",
    ]
    for ch in ("C1", "C3", "C4"):
        assert plot.curves[ch].opts["pen"].color().name().upper() == CHANNEL_COLORS[ch].upper()


def test_side_panel_shows_settings(connected):
    window, fake, qtbot = connected
    panel = window.side_panel
    qtbot.waitUntil(lambda: "mV/div" in panel.channel_labels["C3"].text(), timeout=3000)
    assert "1 V/div" in panel.channel_labels["C1"].text()
    assert "D1M" in panel.channel_labels["C1"].text()
    assert panel.channel_labels["C2"].text() == "(off)"
    assert not panel.checkboxes["C2"].isEnabled()
    assert panel.timebase_label.text() == "100 ns/div"
    assert "Auto" in panel.trigger_label.text()


def test_hiding_a_channel_is_local_only(connected):
    window, fake, qtbot = connected
    n = len(fake.sent)
    window.side_panel.checkboxes["C4"].setChecked(False)
    assert not window.scope_plot.is_curve_visible("C4")
    assert window.scope_plot.is_curve_visible("C1")
    qtbot.wait(300)
    assert all(is_allowed(cmd) for cmd in fake.sent[n:])


def test_pause_freezes_display_but_worker_keeps_running(connected):
    window, fake, qtbot = connected
    window.side_panel.pause_button.click()
    assert window.view.paused
    data_before = window.scope_plot.curves["C1"].getData()[1].copy()
    fake.trigger_seconds = 99.0  # new acquisition at the scope
    n = len(fake.sent)
    qtbot.waitUntil(lambda: any(c.endswith("WF? ALL") for c in fake.sent[n:]), timeout=3000)
    assert (window.scope_plot.curves["C1"].getData()[1] == data_before).all()
    assert "PAUSED" in window.rate_label.text()
    window.side_panel.pause_button.click()
    assert not window.view.paused


def test_no_channels_message(connected):
    window, fake, qtbot = connected
    for ch in ("C1", "C3", "C4"):
        fake.set_reply(f"{ch}:TRA?", f"{ch}:TRA OFF")
    qtbot.waitUntil(lambda: window.scope_plot.no_channels_visible, timeout=3000)


def test_multigrid_note(connected):
    window, fake, qtbot = connected
    fake.set_reply("GRID?", "GRID DUAL")
    qtbot.waitUntil(lambda: window.scope_plot.multigrid_note_visible, timeout=3000)


def test_lost_marks_traces_stale(connected):
    window, fake, qtbot = connected
    fake.fail_after, fake.fail_count = len(fake.sent), None
    qtbot.waitUntil(lambda: window._state is ConnectionState.LOST, timeout=6000)
    assert window.scope_plot.stale_visible
    assert window.scope_plot.is_curve_visible("C1")  # last waveform stays visible
    assert "Lost" in window.connection_bar.status_text.text()


def test_status_bar_rate_and_last_update(connected):
    window, fake, qtbot = connected
    for i in range(4):
        fake.trigger_seconds = 50.0 + i
        qtbot.wait(150)
    assert "updates/s" in window.rate_label.text()
    assert "last update —" not in window.rate_label.text()


def test_disconnect_clears_view(connected):
    window, fake, qtbot = connected
    window.connection_bar.button.click()
    qtbot.waitUntil(lambda: window._state is ConnectionState.DISCONNECTED, timeout=3000)
    assert not window.scope_plot.is_curve_visible("C1")
    assert not window.scope_plot.stale_visible
