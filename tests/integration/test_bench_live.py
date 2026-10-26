"""The synthetic bench behind the real ScopeDriver, worker thread and MainWindow.

Helpers for other tests: the ``bench`` fixture opens a connected window on a ``SyntheticScope``
(``window, scope = bench(scene=..., rate_hz=200, seed=1)``) and closes it at the end.
"""

import numpy as np
import pytest
from pyvisa.errors import VisaIOError
from synthetic_scope import ChannelSetup, Scene, SyntheticScope, synthetic_factory

from scope_gui import driver as driver_module
from scope_gui.driver import ScopeDriver, is_allowed
from scope_gui.models import CHANNELS, ConnectionState
from scope_gui.ui.main_window import MainWindow

FAST = 200.0  # acquisitions per second: keeps the tests quick
SMALL = 2000  # points per record


@pytest.fixture(autouse=True)
def reachable(monkeypatch):
    monkeypatch.setattr(driver_module, "tcp_precheck", lambda host, timeout=3.0: None)


@pytest.fixture
def bench(qtbot):
    """Factory ``bench(scene=None, rate_hz=200, seed=1, connect=True) -> (window, scope)``."""
    windows = []

    def open_bench(scene=None, *, rate_hz=FAST, seed=1, connect=True):
        scope = SyntheticScope(scene or Scene(points=SMALL), rate_hz=rate_hz, seed=seed)
        factory = synthetic_factory(scope)
        window = MainWindow("synthetic", driver_factory=lambda: ScopeDriver(factory))
        windows.append(window)
        qtbot.addWidget(window)
        window.show()
        if connect:
            window.connection_bar.button.click()
            qtbot.waitUntil(lambda: window._state is ConnectionState.CONNECTED, timeout=5000)
            enabled = [n for n, c in scope.scene.channels.items() if c.enabled]
            qtbot.waitUntil(
                lambda: all(window.scope_plot.is_curve_visible(ch) for ch in enabled), timeout=5000
            )
        return window, scope

    yield open_bench
    for window in windows:
        window.close()


def curve(window, channel) -> np.ndarray:
    return np.array(window.scope_plot.curves[channel].getData()[1])


def connected_driver(scope: SyntheticScope) -> ScopeDriver:
    driver = ScopeDriver(synthetic_factory(scope))
    driver.connect("TCPIP0::synthetic::inst0::INSTR")
    return driver


# --- connection ---------------------------------------------------------------------------------
def test_connect_shows_synthetic_identity_without_warning(bench, monkeypatch):
    asked = []
    monkeypatch.setattr(MainWindow, "ask_continue", lambda self, identity: asked.append(identity))
    window, scope = bench()
    text = window.connection_bar.identity_label.text()
    assert "LECROY WR610ZI" in text and "SYNTHETIC" in text
    assert asked == []  # WR610ZI is a supported model: no "unsupported instrument" dialog


def test_all_four_curves_are_drawn_and_change(bench, qtbot):
    window, scope = bench()
    assert [ch for ch in CHANNELS if window.scope_plot.is_curve_visible(ch)] == list(CHANNELS)
    before = {ch: curve(window, ch) for ch in CHANNELS}
    assert all(data.size == SMALL for data in before.values())
    seen = scope.acquisitions
    qtbot.waitUntil(lambda: scope.acquisitions >= seen + 3, timeout=5000)
    qtbot.waitUntil(
        lambda: all(not np.array_equal(curve(window, ch), before[ch]) for ch in CHANNELS),
        timeout=5000,
    )


def test_only_allowlisted_commands_are_written(bench, qtbot):
    window, scope = bench()
    seen = scope.acquisitions
    qtbot.waitUntil(lambda: scope.acquisitions >= seen + 3, timeout=5000)
    assert scope.sent
    assert any(c.endswith("WF? DESC") for c in scope.sent)
    assert any(c.endswith("WF? ALL") for c in scope.sent)
    assert [c for c in scope.sent if not is_allowed(c)] == []


def test_timebase_follows_the_scene(bench):
    scene = Scene(points=SMALL, time_per_div=100e-9, trigger_delay=-300e-9)
    window, scope = bench(scene)
    assert "100 ns/div" in window.side_panel.timebase_label.text()
    times = window.scope_plot.curves["C1"].getData()[0]
    assert times[0] == pytest.approx(-200e-9)  # screen centre at +300 ns, 10 div of 100 ns
    assert times[-1] == pytest.approx(800e-9, rel=1e-3)


def test_disconnect_and_reconnect(bench, qtbot):
    window, scope = bench()
    window.connection_bar.button.click()
    qtbot.waitUntil(lambda: window._state is ConnectionState.DISCONNECTED, timeout=5000)
    assert not window.scope_plot.is_curve_visible("C1")
    window.connection_bar.button.click()
    qtbot.waitUntil(lambda: window._state is ConnectionState.CONNECTED, timeout=5000)
    qtbot.waitUntil(lambda: window.scope_plot.is_curve_visible("C4"), timeout=5000)
    assert [c for c in scope.sent if not is_allowed(c)] == []


# --- acquisitions, below the GUI ----------------------------------------------------------------
def test_channels_of_one_acquisition_share_the_trigger_time():
    scope = SyntheticScope(Scene(points=SMALL), rate_hz=1000, seed=2)
    driver = connected_driver(scope)
    stamps = []
    for _ in range(3):
        desc = driver.read_descriptor("C1")  # starts a new acquisition
        waves = [driver.read_waveform(ch) for ch in CHANNELS]
        assert {w.trigger_time for w in waves} == {desc.trigger_time}
        stamps.append(desc.trigger_time)
    assert stamps == sorted(set(stamps))  # a new trigger time per acquisition, increasing
    assert [c for c in scope.sent if not is_allowed(c)] == []


def test_descriptor_read_does_not_return_samples():
    scope = SyntheticScope(Scene(points=SMALL), rate_hz=1000, seed=2)
    driver = connected_driver(scope)
    desc = driver.read_descriptor("C2")
    assert desc.point_count == SMALL
    assert desc.source == "C2"
    assert desc.vertical_gain == pytest.approx(0.020 / 25)


def test_unknown_command_times_out_like_the_scope():
    scope = SyntheticScope(Scene(points=SMALL), rate_hz=1000)
    with pytest.raises(VisaIOError):
        scope.query("*RST")
    assert scope.sent == ["*RST"]


def test_codes_are_clipped_to_the_screen_edge():
    scene = Scene(points=SMALL, mean_pe=30.0)  # 30 pe = 600 mV on C2
    scene.channels["C2"] = ChannelSetup(0.002, 0.0)  # 2 mV/div: +-10 mV on screen
    scope = SyntheticScope(scene, rate_hz=1000, seed=3)
    driver = connected_driver(scope)
    driver.read_descriptor("C2")
    wave = driver.read_waveform("C2")
    gain = 0.002 / 25
    assert wave.step == pytest.approx(gain)
    assert scope.current.volts["C2"].max() > 0.1  # the real signal is far off screen
    assert wave.volts.max() == pytest.approx(127 * gain, rel=1e-4)  # the decoded one stops
    assert wave.volts.min() >= -128 * gain - 1e-7
    assert np.count_nonzero(wave.volts > 126.5 * gain) > 10  # it sits on the rail


def test_clipping_with_offset_stops_at_edge_minus_offset():
    scene = Scene(points=SMALL, mean_pe=30.0)
    scene.channels["C2"] = ChannelSetup(0.002, -0.001)  # screen centre at +1 mV
    scope = SyntheticScope(scene, rate_hz=1000, seed=3)
    driver = connected_driver(scope)
    driver.read_descriptor("C2")
    wave = driver.read_waveform("C2")
    assert wave.volts.max() == pytest.approx(127 * 0.002 / 25 + 0.001, rel=1e-4)


def test_clipped_curve_in_the_live_view(bench, qtbot):
    scene = Scene(points=SMALL, mean_pe=30.0)
    scene.channels["C2"] = ChannelSetup(0.002, 0.0)
    window, scope = bench(scene)
    y = curve(window, "C2")  # drawn in divisions
    assert y.max() == pytest.approx(127 / 25, rel=1e-3)
    assert y.max() < 5.1


# --- scene changes ------------------------------------------------------------------------------
def test_changing_the_scene_changes_the_next_status_read():
    scope = SyntheticScope(Scene(points=SMALL), rate_hz=1000)
    driver = connected_driver(scope)
    before = driver.read_status()
    scope.scene.channels["C2"].volts_per_div = 0.050
    scope.scene.time_per_div = 20e-9
    after = driver.read_status()
    assert before.channel("C2").volts_per_div == pytest.approx(0.020)
    assert after.channel("C2").volts_per_div == pytest.approx(0.050)
    assert after.acquisition.time_per_div == pytest.approx(20e-9)
    assert before.channel("C3") == after.channel("C3")


# --- launcher -----------------------------------------------------------------------------------
def test_bench_launcher_builds_an_isolated_window(qtbot, monkeypatch, tmp_path):
    import bench  # tests/bench.py

    # build_window replaces these process-wide; monkeypatch restores them afterwards.
    monkeypatch.setattr(driver_module, "tcp_precheck", driver_module.tcp_precheck)
    args = bench.parse_args(["--rate", "200", "--points", "2000", "--seed", "5", "--mean-pe", "7"])
    assert (args.rate, args.points, args.seed, args.mean_pe) == (200.0, 2000, 5, 7.0)
    window, scope = bench.build_window(args)
    qtbot.addWidget(window)
    try:
        assert window.windowTitle() == "Scope GUI — SYNTHETIC test bench"
        assert (scope.scene.points, scope.scene.mean_pe, scope.rate_hz) == (2000, 7.0, 200.0)
        window.show()
        window.connection_bar.button.click()
        qtbot.waitUntil(lambda: window._state is ConnectionState.CONNECTED, timeout=5000)
        qtbot.waitUntil(lambda: window.scope_plot.is_curve_visible("C4"), timeout=5000)
        assert (tmp_path / "scope_gui" / "bench.ini").exists()  # its own settings file
        assert "synthetic" in (tmp_path / "scope_gui" / "bench.ini").read_text()
    finally:
        window.close()
