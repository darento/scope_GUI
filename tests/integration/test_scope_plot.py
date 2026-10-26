import numpy as np
import pytest

from scope_gui.models import (
    AcqState,
    AcquisitionSettings,
    ChannelSettings,
    ScopeStatus,
    TriggerMode,
    Waveform,
    volts_to_div,
    x_range,
)
from scope_gui.ui.scope_plot import ScopePlot

CHANNEL_DEFAULTS = {
    "C1": (1.0, -3.01),
    "C2": (1.0, 0.0),
    "C3": (0.5, -0.485),
    "C4": (0.5, -0.485),
}


def make_status(enabled=("C1", "C3", "C4"), grid="SINGLE", volts_per_div=None) -> ScopeStatus:
    channels = []
    for name, (vdiv, offset) in CHANNEL_DEFAULTS.items():
        if volts_per_div and name in volts_per_div:
            vdiv = volts_per_div[name]
        channels.append(ChannelSettings(name, name in enabled, vdiv, offset, "DC1M"))
    acq = AcquisitionSettings(100e-9, -184e-9, TriggerMode.AUTO, grid)
    return ScopeStatus(tuple(channels), acq, AcqState.ACQUIRING, 0.0)


def make_waveform(name="C1", points=10_000, amplitude=1.0) -> Waveform:
    t0, span = -316e-9, 1e-6
    dt = span / points
    volts = amplitude * np.sin(np.linspace(0, 20 * np.pi, points))
    return Waveform(name, volts, t0, dt, 0.0, 0.0)


def all_waveforms(**kwargs) -> dict[str, Waveform]:
    return {name: make_waveform(name, **kwargs) for name in CHANNEL_DEFAULTS}


def point_count(curve) -> int:
    x = curve.xData  # the full trace (getData() is downsampled)
    return 0 if x is None else len(x)


@pytest.fixture
def plot(qtbot):
    widget = ScopePlot()
    qtbot.addWidget(widget)
    widget.resize(800, 500)
    return widget


def test_ranges_follow_scope_screen(plot):
    status = make_status()
    plot.set_status(status)
    x, y = plot.plot.viewRange()
    expected = x_range(status.acquisition)
    assert x == pytest.approx(expected)
    assert x == pytest.approx((-316e-9, 684e-9))
    assert y == pytest.approx([-4, 4])


def test_ranges_update_when_timebase_changes(plot):
    plot.set_status(make_status())
    acq = AcquisitionSettings(1e-6, 0.0, TriggerMode.AUTO, "SINGLE")
    plot.set_status(ScopeStatus(make_status().channels, acq, AcqState.ACQUIRING, 0.0))
    assert plot.plot.viewRange()[0] == pytest.approx([-5e-6, 5e-6])


def test_graticule_has_a_line_at_every_division(plot):
    status = make_status()
    plot.set_status(status)
    xs, ys = plot._grid.getData()
    cx, cy = plot._grid_centre.getData()
    x_min, x_max = x_range(status.acquisition)

    vertical = {
        round(x, 15) for x, y1, y2 in zip(xs[::2], ys[::2], ys[1::2], strict=True) if y1 != y2
    }
    vertical |= {
        round(x, 15) for x, y1, y2 in zip(cx[::2], cy[::2], cy[1::2], strict=True) if y1 != y2
    }
    expected = {round(x_min + k * 100e-9, 15) for k in range(11)}
    assert vertical == expected

    horizontal = sorted(
        {y for y, x1, x2 in zip(ys[::2], xs[::2], xs[1::2], strict=True) if x1 != x2}
        | {y for y, x1, x2 in zip(cy[::2], cx[::2], cx[1::2], strict=True) if x1 != x2}
    )
    assert horizontal == list(range(-4, 5))


def test_only_enabled_channels_visible(plot):
    plot.set_status(make_status(enabled=("C1", "C3", "C4")))
    plot.set_waveforms(all_waveforms())
    assert [n for n in plot.curves if plot.is_curve_visible(n)] == ["C1", "C3", "C4"]
    assert [n for n, c in plot.curves.items() if c.isVisible()] == ["C1", "C3", "C4"]
    assert point_count(plot.curves["C2"]) == 0


def test_waveforms_before_status_are_ignored(plot):
    plot.set_waveforms(all_waveforms())
    plot.set_status(make_status())
    assert not any(plot.is_curve_visible(n) for n in plot.curves)


def test_curve_data_is_in_divisions(plot):
    status = make_status()
    plot.set_status(status)
    waveforms = all_waveforms()
    plot.set_waveforms(waveforms)
    for name in ("C1", "C3"):
        curve = plot.curves[name]  # xData/yData: the full trace (getData() is downsampled)
        np.testing.assert_allclose(
            curve.yData, volts_to_div(waveforms[name].volts, status.channel(name))
        )
        np.testing.assert_allclose(curve.xData, waveforms[name].times)


def test_missing_channel_keeps_old_data(plot):
    plot.set_status(make_status())
    plot.set_waveforms(all_waveforms())
    plot.set_waveforms({"C1": make_waveform("C1", points=500)})
    assert plot.curves["C1"].yData.size == 500
    assert plot.curves["C3"].yData.size == 10_000
    assert plot.is_curve_visible("C3")


def test_channel_setting_change_redraws_with_new_scale(plot):
    plot.set_status(make_status())
    waveforms = all_waveforms()
    plot.set_waveforms(waveforms)
    status = make_status(volts_per_div={"C1": 2.0})
    plot.set_status(status)
    np.testing.assert_allclose(
        plot.curves["C1"].yData, volts_to_div(waveforms["C1"].volts, status.channel("C1"))
    )


def test_channel_turned_off_drops_data(plot):
    plot.set_status(make_status())
    plot.set_waveforms(all_waveforms())
    plot.set_status(make_status(enabled=("C1",)))
    assert plot.is_curve_visible("C1")
    assert not plot.is_curve_visible("C3")
    plot.set_status(make_status())
    assert not plot.is_curve_visible("C3")


def test_set_hidden_hides_only_that_curve(plot):
    plot.set_status(make_status())
    plot.set_waveforms(all_waveforms())
    plot.set_hidden({"C3"})
    assert plot.is_curve_visible("C1")
    assert not plot.is_curve_visible("C3")
    assert plot.is_curve_visible("C4")
    assert not plot.curves["C3"].isVisible()
    plot.set_hidden(set())
    assert plot.is_curve_visible("C3")
    assert plot.curves["C3"].isVisible()


def test_no_channels_overlay(plot):
    assert not plot.no_channels_visible
    plot.set_status(make_status(enabled=()))
    assert plot.no_channels_visible
    plot.set_status(make_status())
    assert not plot.no_channels_visible


def test_multigrid_note(plot):
    plot.set_status(make_status(grid="SINGLE"))
    assert not plot.multigrid_note_visible
    plot.set_status(make_status(grid="XY"))
    assert plot.multigrid_note_visible
    plot.set_status(make_status(grid="single"))
    assert not plot.multigrid_note_visible


def test_stale_overlay_and_opacity(plot):
    plot.set_status(make_status())
    plot.set_waveforms(all_waveforms())
    assert not plot.stale_visible
    plot.set_stale(True)
    assert plot.stale_visible
    assert all(c.opacity() == pytest.approx(0.4) for c in plot.curves.values())
    plot.set_waveforms(all_waveforms())
    assert plot.curves["C1"].opacity() == pytest.approx(0.4)
    plot.set_stale(False)
    assert not plot.stale_visible
    assert all(c.opacity() == pytest.approx(1.0) for c in plot.curves.values())


def test_clear_resets_everything(plot):
    plot.set_status(make_status(enabled=(), grid="XY"))
    plot.set_stale(True)
    plot.set_status(make_status(grid="XY"))
    plot.set_waveforms(all_waveforms())
    plot.set_stale(True)
    plot.clear()
    assert not any(plot.is_curve_visible(n) for n in plot.curves)
    assert not any(c.isVisible() for c in plot.curves.values())
    assert all(point_count(c) == 0 for c in plot.curves.values())
    assert not plot.stale_visible
    assert not plot.no_channels_visible
    assert not plot.multigrid_note_visible
    assert all(c.opacity() == pytest.approx(1.0) for c in plot.curves.values())
    plot.set_waveforms(all_waveforms())
    assert not any(plot.is_curve_visible(n) for n in plot.curves)


def test_large_waveform_is_accepted(plot, qtbot):
    plot.set_status(make_status())
    plot.show()
    qtbot.waitExposed(plot)
    plot.set_waveforms({"C1": make_waveform("C1", points=500_000)})
    assert plot.curves["C1"].yData.size == 500_000
    plot.grab()
    assert plot.plot.viewRange()[0] == pytest.approx([-316e-9, 684e-9])


def test_hover_readout_shows_time_and_volts(plot):
    status = make_status()
    plot.set_status(status)
    plot.set_waveforms(all_waveforms())
    plot.set_hidden({"C4"})
    plot.show_readout(0.0, 1.0)
    text = plot.hover_text
    assert "C1 = " in text and "C3 = " in text
    assert "C4" not in text and "C2" not in text
    assert "t = " in text
    # C1 at +1 div: 1 V/div, offset -3.01 V -> 1 + 3.01 = 4.01 V
    assert "C1 = 4.01 V" in text


def test_hover_hidden_without_status(plot):
    plot.show_readout(0.0, 0.0)
    assert plot.hover_text == ""


def test_all_pens_are_cosmetic(qtbot):
    """A non-cosmetic pen is sized in data units and floods a nanosecond time axis."""
    plot = ScopePlot()
    qtbot.addWidget(plot)
    pens = [plot.trigger_line.pen, plot._grid.opts["pen"], plot._grid_centre.opts["pen"]]
    pens += [curve.opts["pen"] for curve in plot.curves.values()]
    assert all(pen.isCosmetic() for pen in pens)
