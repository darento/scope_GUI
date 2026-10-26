"""Zoom, cursors, gate and level lines on the scope plot (002 contracts/ui.md, research R8, R9)."""

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication
from test_scope_plot import make_status

from scope_gui.analysis import Edge, Kind, Level, MeasurementSpec
from scope_gui.models import Waveform, volts_to_div, x_range
from scope_gui.ui.scope_plot import ScopePlot


@pytest.fixture
def plot(qtbot):
    widget = ScopePlot()
    qtbot.addWidget(widget)
    widget.resize(800, 500)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def ramp(name: str, slope: float = 1e7) -> Waveform:
    """volts = slope * t over -316 ns ... +684 ns (1 ns samples)."""
    t0, dt = -316e-9, 1e-9
    t = t0 + np.arange(1000) * dt
    return Waveform(name, (slope * t).astype(np.float32), t0, dt, 0.0, 0.0)


def view_x(plot) -> tuple[float, float]:
    return tuple(plot.plot.vb.viewRange()[0])


def wheel(plot, steps: int = 1) -> None:
    viewport = plot.plot_widget.viewport()
    centre = QPointF(viewport.width() / 2, viewport.height() / 2)
    event = QWheelEvent(
        centre,
        viewport.mapToGlobal(centre),
        QPoint(0, 0),
        QPoint(0, 120 * steps),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(viewport, event)


# --- zoom (FR-014) --------------------------------------------------------------------------------


def test_wheel_zoom_is_kept_while_the_scope_updates(plot):
    status = make_status()
    plot.set_status(status)
    screen = x_range(status.acquisition)
    assert view_x(plot) == pytest.approx(screen)
    wheel(plot, 2)
    assert plot.zoomed
    zoomed = view_x(plot)
    assert zoomed[1] - zoomed[0] < screen[1] - screen[0]
    plot.set_status(make_status(volts_per_div={"C1": 2.0}))
    plot.set_waveforms({"C1": ramp("C1")})
    assert view_x(plot) == pytest.approx(zoomed)


def test_reset_view_follows_the_scope_again(plot):
    status = make_status()
    plot.set_status(status)
    wheel(plot, 2)
    plot.reset_view()
    assert not plot.zoomed
    assert view_x(plot) == pytest.approx(x_range(status.acquisition))
    assert tuple(plot.plot.vb.viewRange()[1]) == pytest.approx((-4, 4))


def double_click(plot) -> None:
    # Explicit events: pyqtgraph's scene ignores QTest's synthetic double-click sequence.
    viewport = plot.plot_widget.viewport()
    centre = QPointF(viewport.rect().center())
    left = Qt.MouseButton.LeftButton
    for kind in (
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonRelease,
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.MouseButtonRelease,
    ):
        held = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else left
        event = QMouseEvent(
            kind, centre, viewport.mapToGlobal(centre), left, held, Qt.KeyboardModifier.NoModifier
        )
        QApplication.sendEvent(viewport, event)


def test_double_click_resets_the_view(plot):
    plot.set_status(make_status())
    wheel(plot, 2)
    double_click(plot)
    assert not plot.zoomed


def test_mouse_modes():
    widget = ScopePlot()
    vb = widget.plot.vb
    assert vb.state["mouseMode"] == vb.RectMode  # left-drag: box zoom
    assert vb.state["mouseEnabled"] == [True, True]
    assert not widget.plot.menuEnabled()


# --- cursors (FR-015) -----------------------------------------------------------------------------


def test_cursors_start_at_thirds_of_the_view(plot):
    plot.set_status(make_status())
    x_min, x_max = view_x(plot)
    plot.set_cursors_visible(True)
    t1, t2 = plot.cursor_positions()
    assert t1 == pytest.approx(x_min + (x_max - x_min) / 3)
    assert t2 == pytest.approx(x_min + 2 * (x_max - x_min) / 3)
    plot.set_cursors_visible(False)
    assert plot.cursor_text == ""


def test_cursor_readout_values_from_the_waveform(plot):
    plot.set_status(make_status(enabled=("C1", "C3")))
    plot.set_waveforms({"C1": ramp("C1"), "C3": ramp("C3", slope=-2e7)})
    plot.set_cursors_visible(True)
    plot.set_cursor_positions(100.5e-9, 200.5e-9)  # between samples: interpolated
    text = plot.cursor_text
    assert "Δt = 100 ns" in text
    assert "1/Δt = 10 MHz" in text
    assert "C1  1.005 V  2.005 V  Δ 1 V" in text
    assert "C3  -2.01 V  -4.01 V  Δ -2 V" in text
    assert "C2" not in text and "C4" not in text  # only visible channels


def test_cursor_readout_follows_new_waveforms_and_drags(plot):
    plot.set_status(make_status(enabled=("C1",)))
    plot.set_waveforms({"C1": ramp("C1")})
    plot.set_cursors_visible(True)
    plot.set_cursor_positions(0.0, 100e-9)
    assert "C1  0 V  1 V" in plot.cursor_text
    plot.set_waveforms({"C1": ramp("C1", slope=2e7)})
    assert "C1  0 V  2 V" in plot.cursor_text
    plot.cursors[1].setValue(50e-9)
    assert "Δt = 50 ns" in plot.cursor_text


def test_cursor_outside_the_record_shows_a_dash(plot):
    plot.set_status(make_status(enabled=("C1",)))
    plot.set_waveforms({"C1": ramp("C1")})
    plot.set_cursors_visible(True)
    plot.set_cursor_positions(-500e-9, 0.0)
    assert "C1  —" in plot.cursor_text


# --- gate (FR-016) --------------------------------------------------------------------------------


def test_gate_between_cursors(plot):
    plot.set_status(make_status())
    assert plot.gate() is None
    plot.set_gate_enabled(True)
    assert plot.cursors_visible and plot.gate_visible
    plot.set_cursor_positions(300e-9, 100e-9)
    assert plot.gate() == pytest.approx((100e-9, 300e-9))
    assert plot.gate_region.getRegion() == pytest.approx((100e-9, 300e-9))
    assert not plot.gate_region.movable
    plot.set_cursors_visible(False)  # no cursors, no gate
    assert plot.gate() is None and not plot.gate_visible


# --- level lines (FR-017) -------------------------------------------------------------------------

DT_SPEC = MeasurementSpec(Kind.DELTA_T, "C1", Level(1.25), "C3", Level(-0.2, edge=Edge.FALLING))


def test_level_lines_in_channel_colour_at_the_right_division(plot):
    status = make_status()
    plot.set_status(status)
    plot.set_level_lines(DT_SPEC)
    first, second = plot.level_lines
    assert first.value() == pytest.approx(volts_to_div(1.25, status.channel("C1")))
    assert second.value() == pytest.approx(volts_to_div(-0.2, status.channel("C3")))
    assert first.pen.color().name().upper() == "#F5E400"
    assert first.movable


def test_relative_levels_and_level_free_kinds_draw_nothing(plot):
    plot.set_status(make_status())
    plot.set_level_lines(MeasurementSpec(Kind.DELTA_T, "C2", Level(0.2, True), "C3", Level(0.03)))
    assert len(plot.level_lines) == 1
    plot.set_level_lines(MeasurementSpec(Kind.AMPLITUDE, "C2"))
    assert plot.level_lines == []
    plot.set_level_lines(None)
    assert plot.level_lines == []


def test_dragging_a_level_emits_volts_on_release_only(plot, qtbot):
    status = make_status()
    plot.set_status(status)
    plot.set_level_lines(DT_SPEC)
    line = plot.level_lines[1]  # C3, 0.5 V/div, offset -0.485 V
    emitted = []
    plot.level_dragged.connect(lambda index, volts: emitted.append((index, volts)))
    line.setValue(1.0)
    line.sigDragged.emit(line)
    assert emitted == []
    # A scale update while dragging keeps the dragged volts, not the old level.
    plot.set_status(make_status(volts_per_div={"C3": 1.0}))
    line.sigPositionChangeFinished.emit(line)
    expected = 1.0 * 0.5 - (-0.485)
    assert emitted == [(1, pytest.approx(expected))]


def test_level_lines_follow_scale_changes(plot):
    plot.set_status(make_status())
    plot.set_level_lines(DT_SPEC)
    status = make_status(volts_per_div={"C1": 2.0})
    plot.set_status(status)
    assert plot.level_lines[0].value() == pytest.approx(volts_to_div(1.25, status.channel("C1")))


# --- disconnect -----------------------------------------------------------------------------------


def test_clear_keeps_zoom_and_cursors(plot):
    plot.set_status(make_status())
    wheel(plot, 2)
    plot.set_cursors_visible(True)
    plot.clear()
    assert plot.zoomed and plot.cursors_visible


# --- persistence (FR-018, research R7) ------------------------------------------------------------


def feed(plot, n: int = 1, **status) -> None:
    from test_scope_plot import all_waveforms

    plot.set_status(make_status(**status))
    for _ in range(n):
        plot.set_waveforms(all_waveforms())


def test_persistence_off_by_default(plot):
    feed(plot)
    assert plot.persistence is None and not plot.persistence_image.isVisible()


def test_persistence_draws_behind_the_traces(plot, qtbot):
    plot.set_persistence(100)
    feed(plot, 3)
    assert plot.persistence.count == 3
    image = plot.persistence_image
    assert image.image is None  # repainted at most every PERSISTENCE_REPAINT_MS, not per trace
    qtbot.waitUntil(lambda: image.image is not None, timeout=1000)
    assert image.isVisible() and image.image[..., 3].any()
    assert image.zValue() < min(curve.zValue() for curve in plot.curves.values())
    rect = image.mapRectToParent(image.boundingRect())
    (x0, x1), (y0, y1) = plot.plot.vb.viewRange()
    assert (rect.left(), rect.right()) == pytest.approx((x0, x1))
    assert (rect.top(), rect.bottom()) == pytest.approx((y0, y1))


def test_persistence_restarts_on_zoom_reset_and_scale_change(plot):
    plot.set_persistence(None)
    feed(plot, 2)
    wheel(plot, 2)
    assert plot.persistence.count == 0
    feed(plot, 2)
    plot.reset_view()
    assert plot.persistence.count == 0
    feed(plot, 2)
    feed(plot, 0, volts_per_div={"C1": 2.0})
    assert plot.persistence.count == 0


def test_persistence_depth_change_keeps_the_map_and_off_removes_it(plot):
    plot.set_persistence(10)
    feed(plot, 2)
    plot.set_persistence(1000)
    assert plot.persistence.count == 2
    plot.set_persistence(0)
    assert plot.persistence is None and not plot.persistence_image.isVisible()


def test_clear_empties_persistence(plot):
    plot.set_persistence(100)
    feed(plot, 2)
    plot.clear()
    assert plot.persistence.count == 0
    plot.set_waveforms({"C1": ramp("C1")})  # no status: nothing added
    assert plot.persistence.count == 0
