"""Plot mirroring the scope's screen: 10 x 8 divisions, scope trace colours (research R6, R7).

Analysis tools (spec 002, research R7-R9): box/wheel zoom and pan with a way back to the scope's
screen, two time cursors with a readout, the measurement gate between them, draggable level lines
of the selected measurement and a fading density persistence behind the traces.
"""

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..analysis import Kind, MeasurementSpec
from ..analysis import si_format as _si
from ..models import (
    CHANNEL_COLORS,
    CHANNELS,
    Y_RANGE_DIV,
    ScopeStatus,
    Waveform,
    div_to_volts,
    volts_to_div,
    x_range,
)
from .persistence import Persistence

pg.setConfigOptions(antialias=False)

STALE_OPACITY = 0.4
GRID_COLOR = "#3c3c3c"
GRID_CENTRE_COLOR = "#6a6a6a"
TRIGGER_COLOR = "#ff9a1f"
CURSOR_COLOR = "#e0e0e0"
GATE_BRUSH = (255, 255, 255, 28)
OVERLAY_MARGIN = 8

NO_CHANNELS_TEXT = "No channels enabled on the scope"
MULTIGRID_TEXT = "Scope uses a multi-grid layout; shown here on one grid"
STALE_TEXT = "STALE — not live"


def _overlay(parent: QWidget, text: str, style: str) -> QLabel:
    label = QLabel(text, parent)
    label.setStyleSheet(style)
    label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    label.adjustSize()
    label.hide()
    return label


class ScopePlot(QWidget):
    level_dragged = Signal(int, float)  # level index (0 or 1) of the selected measurement, volts
    PERSISTENCE_Z = -8  # above the grid, below the traces
    PERSISTENCE_REPAINT_MS = 100  # image() costs 10-25 ms: not for every acquisition

    def __init__(self, parent=None):
        super().__init__(parent)
        self._status: ScopeStatus | None = None
        self._waveforms: dict[str, Waveform] = {}
        self._ramp_key: tuple[int, float] | None = None  # (points, dt) of self._ramp
        self._ramp = np.empty(0)  # i * dt; the trace times are t0 + this
        self._hidden: set[str] = set()
        self._stale = False
        self._grid_x: tuple[float, float, float] | None = None
        self.zoomed = False  # the user owns the view range until Reset view (research R8)
        self._gate_on = False
        self._level_lines: list[tuple[pg.InfiniteLine, int, str]] = []
        self._level_volts: dict[int, float] = {}
        self.persistence: Persistence | None = None  # None: persistence off

        self.plot_widget = pg.PlotWidget(background="k")
        self.plot: pg.PlotItem = self.plot_widget.getPlotItem()
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        # Set on the PlotItem: its addItem() overwrites a curve's own downsampling and clipping.
        # Peak downsampling draws ~5 points per pixel (2.5M-point traces: ~1 s -> ~0.1 s a frame).
        self.plot.setDownsampling(auto=True, mode="peak")
        self.plot.setClipToView(True)
        # Left-drag: box zoom; wheel: zoom; middle-drag: pan (FR-014). No context menu: its
        # options would fight with the scope mirror.
        self.plot.setMouseEnabled(True, True)
        self.plot.vb.setMouseMode(pg.ViewBox.RectMode)
        self.plot.vb.sigRangeChangedManually.connect(self._on_manual_range)
        self.plot_widget.scene().sigMouseClicked.connect(self._on_mouse_clicked)
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.setLabel("left", "div")
        self.plot.setXRange(-0.5, 0.5, padding=0)
        self.plot.setYRange(*Y_RANGE_DIV, padding=0)
        self.plot.disableAutoRange()

        self._grid = pg.PlotCurveItem(pen=pg.mkPen(GRID_COLOR), connect="pairs")
        self._grid_centre = pg.PlotCurveItem(
            pen=pg.mkPen(GRID_CENTRE_COLOR, style=Qt.PenStyle.DotLine), connect="pairs"
        )
        for item in (self._grid, self._grid_centre):
            item.setZValue(-10)
            self.plot.addItem(item, ignoreBounds=True)

        self.curves: dict[str, pg.PlotDataItem] = {}
        for name in CHANNELS:
            curve = pg.PlotDataItem(pen=pg.mkPen(CHANNEL_COLORS[name]))
            curve.setVisible(False)
            self.plot.addItem(curve, ignoreBounds=True)
            self.curves[name] = curve

        # mkPen is cosmetic (1 px); a plain QPen would be 1 *second* wide on this time axis.
        trigger_pen = pg.mkPen(TRIGGER_COLOR, style=Qt.PenStyle.DashLine)
        self.trigger_line = pg.InfiniteLine(
            pos=0,
            angle=90,
            movable=False,
            pen=trigger_pen,
            label="T",
            labelOpts={"position": 0.97, "color": TRIGGER_COLOR, "anchors": [(0.5, 1), (0.5, 1)]},
        )
        self.trigger_line.setZValue(-5)
        self.plot.addItem(self.trigger_line, ignoreBounds=True)

        # Fading density of recent acquisitions behind the traces (FR-018, research R7).
        self.persistence_image = pg.ImageItem(axisOrder="row-major")
        self.persistence_image.setZValue(self.PERSISTENCE_Z)
        self.persistence_image.setVisible(False)
        self.plot.addItem(self.persistence_image, ignoreBounds=True)
        self._persistence_timer = QTimer(self)
        self._persistence_timer.setSingleShot(True)
        self._persistence_timer.setInterval(self.PERSISTENCE_REPAINT_MS)
        self._persistence_timer.timeout.connect(self._paint_persistence)

        # Measurement gate: shaded, follows the cursors, not draggable itself (FR-016).
        self.gate_region = pg.LinearRegionItem(movable=False, brush=pg.mkBrush(*GATE_BRUSH))
        self.gate_region.setZValue(-6)
        self.gate_region.setVisible(False)
        self.plot.addItem(self.gate_region, ignoreBounds=True)

        # Two time cursors (FR-015).
        self.cursors: list[pg.InfiniteLine] = []
        for label in ("1", "2"):
            line = pg.InfiniteLine(
                angle=90,
                movable=True,
                pen=pg.mkPen(CURSOR_COLOR, style=Qt.PenStyle.DashDotLine),
                hoverPen=pg.mkPen(CURSOR_COLOR, width=2),
                label=label,
                labelOpts={"position": 0.03, "color": CURSOR_COLOR},
            )
            line.setVisible(False)
            line.sigPositionChanged.connect(self._on_cursor_moved)
            self.plot.addItem(line, ignoreBounds=True)
            self.cursors.append(line)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot_widget)

        self._no_channels = _overlay(
            self.plot_widget, NO_CHANNELS_TEXT, "color: #b0b0b0; font-size: 16pt;"
        )
        self._multigrid = _overlay(
            self.plot_widget, MULTIGRID_TEXT, "color: #f0a020; font-size: 9pt;"
        )
        self._stale_label = _overlay(
            self.plot_widget,
            STALE_TEXT,
            "color: #ff4040; font-size: 14pt; font-weight: bold;"
            " background: rgba(0, 0, 0, 160); padding: 2px 8px;",
        )
        self._hover = _overlay(
            self.plot_widget,
            "",
            "color: #e0e0e0; font-family: Consolas, monospace; font-size: 9pt;"
            " background: rgba(0, 0, 0, 170); padding: 2px 6px;",
        )
        self._hover.setTextFormat(Qt.TextFormat.RichText)
        self._cursor_readout = _overlay(
            self.plot_widget,
            "",
            "color: #e0e0e0; font-family: Consolas, monospace; font-size: 9pt;"
            " background: rgba(0, 0, 0, 170); padding: 2px 6px;",
        )
        self._cursor_readout.setTextFormat(Qt.TextFormat.RichText)

        self._proxy = pg.SignalProxy(
            self.plot_widget.scene().sigMouseMoved, rateLimit=30, slot=self._on_mouse_moved
        )
        self.plot.vb.sigResized.connect(self._layout_overlays)
        self.plot_widget.installEventFilter(self)
        self.plot_widget.viewport().installEventFilter(self)

    # -- public API ---------------------------------------------------------------------

    def set_status(self, status: ScopeStatus) -> None:
        previous = self._status
        self._status = status
        self._update_range(status)

        for name in CHANNELS:
            settings = status.channel(name)
            if not settings.enabled:
                if name in self._waveforms:
                    del self._waveforms[name]
                    self.curves[name].setData([], [])
            elif previous is None or previous.channel(name) != settings:
                self._draw(name)
        self._refresh_visibility()

        self._no_channels.setVisible(not status.enabled_channels)
        self._multigrid.setVisible(status.acquisition.grid_mode.upper() != "SINGLE")
        self._place_level_lines()
        if previous is not None and _scales(previous) != _scales(status):
            self._restart_persistence()
        self._layout_overlays()

    def set_waveforms(self, waveforms: dict[str, Waveform]) -> None:
        if self._status is None:
            return
        enabled = self._status.enabled_channels
        for name, waveform in waveforms.items():
            if name in enabled and name in self.curves:
                self._waveforms[name] = waveform
                self._draw(name)
        self._refresh_visibility()
        self._update_cursor_readout()
        self._add_persistence()

    def set_hidden(self, hidden: set[str]) -> None:
        self._hidden = set(hidden)
        self._refresh_visibility()

    def set_stale(self, stale: bool) -> None:
        self._stale = stale
        opacity = STALE_OPACITY if stale else 1.0
        for curve in self.curves.values():
            curve.setOpacity(opacity)
        self._stale_label.setVisible(stale)
        self._layout_overlays()

    def clear(self) -> None:
        """Disconnected: traces and persistence go; zoom, cursors and gate stay (ui.md)."""
        self._status = None
        self._waveforms.clear()
        self._restart_persistence()
        self._update_cursor_readout()
        for curve in self.curves.values():
            curve.setData([], [])
            curve.setVisible(False)
        self.set_stale(False)
        self._no_channels.hide()
        self._multigrid.hide()
        self._hover.hide()

    def is_curve_visible(self, name: str) -> bool:
        return (
            self._status is not None
            and self._status.channel(name).enabled
            and name not in self._hidden
            and name in self._waveforms
        )

    # -- zoom (FR-014, research R8) -----------------------------------------------------------

    def reset_view(self) -> None:
        """Back to the scope's screen; the view follows the scope again."""
        self.zoomed = False
        if self._status is not None:
            self._update_range(self._status)
        self._restart_persistence()

    def _on_manual_range(self, *_args) -> None:
        self.zoomed = True
        self._restart_persistence()

    def _on_mouse_clicked(self, event) -> None:
        if event.double() and self.plot.vb.sceneBoundingRect().contains(event.scenePos()):
            event.accept()
            self.reset_view()

    # -- cursors and gate (FR-015, FR-016, research R9) ----------------------------------------

    @property
    def cursors_visible(self) -> bool:
        return self.cursors[0].isVisible()

    def set_cursors_visible(self, visible: bool) -> None:
        if visible and not self.cursors_visible:
            (x_min, x_max), _ = self.plot.vb.viewRange()
            for line, fraction in zip(self.cursors, (1 / 3, 2 / 3), strict=True):
                line.setValue(x_min + fraction * (x_max - x_min))
        for line in self.cursors:
            line.setVisible(visible)
        if not visible:
            self.set_gate_enabled(False)
        self._update_cursor_readout()

    def cursor_positions(self) -> tuple[float, float]:
        return self.cursors[0].value(), self.cursors[1].value()

    def set_cursor_positions(self, t1: float, t2: float) -> None:
        self.cursors[0].setValue(t1)
        self.cursors[1].setValue(t2)

    def set_gate_enabled(self, enabled: bool) -> None:
        """Measure only between the cursors; switching the gate on shows the cursors."""
        self._gate_on = enabled
        if enabled and not self.cursors_visible:
            self.set_cursors_visible(True)
        self.gate_region.setVisible(enabled)
        self._follow_cursors()

    @property
    def gate_visible(self) -> bool:
        return self.gate_region.isVisible()

    def gate(self) -> tuple[float, float] | None:
        """The measurement gate (t1 <= t2), or None for the whole record."""
        if not self._gate_on:
            return None
        t1, t2 = sorted(self.cursor_positions())
        return t1, t2

    def _on_cursor_moved(self, _line=None) -> None:
        self._follow_cursors()
        self._update_cursor_readout()

    def _follow_cursors(self) -> None:
        if self._gate_on:
            self.gate_region.setRegion(sorted(self.cursor_positions()))

    def _update_cursor_readout(self) -> None:
        if not self.cursors_visible:
            self._cursor_readout.hide()
            return
        t1, t2 = self.cursor_positions()
        delta = t2 - t1
        inverse = 1 / delta if delta else math.nan
        lines = [f"Δt = {_si(delta, 's')}   1/Δt = {_si(inverse, 'Hz')}"]
        for name in CHANNELS:
            waveform = self._waveforms.get(name)
            if waveform is None or not self.is_curve_visible(name):
                continue
            v1, v2 = (_value_at(waveform, t) for t in (t1, t2))
            text = f"{name}  {_si(v1, 'V')}  {_si(v2, 'V')}  Δ {_si(v2 - v1, 'V')}"
            lines.append(f'<span style="color: {CHANNEL_COLORS[name]}">{text}</span>')
        self._cursor_readout.setText("<br>".join(lines))
        self._cursor_readout.show()
        self._layout_overlays()

    @property
    def cursor_text(self) -> str:
        return "" if self._cursor_readout.isHidden() else self._cursor_readout.text()

    # -- level lines (FR-017) ------------------------------------------------------------------

    def set_level_lines(self, spec: MeasurementSpec | None) -> None:
        """Dashed lines for the volt levels of the selected measurement, in channel colours."""
        for line, _index, _channel in self._level_lines:
            self.plot.removeItem(line)
        self._level_lines.clear()
        self._level_volts.clear()
        if spec is None:
            return
        levels = [(0, spec.source, spec.level)] if spec.kind.levels >= 1 else []
        if spec.kind is Kind.DELTA_T:
            levels.append((1, spec.source2, spec.level2))
        for index, channel, level in levels:
            if level.relative:
                continue
            color = CHANNEL_COLORS[channel]
            line = pg.InfiniteLine(
                angle=0,
                movable=True,
                pen=pg.mkPen(color, style=Qt.PenStyle.DashLine),
                hoverPen=pg.mkPen(color, width=2),
                label=f"{channel} {level.label()}",
                labelOpts={"position": 0.92, "color": color, "anchors": [(1, 1), (1, 1)]},
            )
            line.sigDragged.connect(lambda ln, i=index, ch=channel: self._on_level_drag(ln, i, ch))
            line.sigPositionChangeFinished.connect(lambda _ln, i=index: self._on_level_done(i))
            self.plot.addItem(line, ignoreBounds=True)
            self._level_lines.append((line, index, channel))
            self._level_volts[index] = level.value
        self._place_level_lines()

    @property
    def level_lines(self) -> list[pg.InfiniteLine]:
        return [line for line, _index, _channel in self._level_lines]

    def _place_level_lines(self) -> None:
        for line, index, channel in self._level_lines:
            line.setVisible(self._status is not None)
            if self._status is not None:
                div = volts_to_div(self._level_volts[index], self._status.channel(channel))
                line.blockSignals(True)
                line.setValue(div)
                line.blockSignals(False)

    def _on_level_drag(self, line: pg.InfiniteLine, index: int, channel: str) -> None:
        # Keep the dragged value in volts so a scale update does not snap the line back.
        if self._status is not None:
            settings = self._status.channel(channel)
            self._level_volts[index] = float(div_to_volts(line.value(), settings))

    def _on_level_done(self, index: int) -> None:
        if index in self._level_volts:
            self.level_dragged.emit(index, self._level_volts[index])

    # -- persistence (FR-018) ------------------------------------------------------------------

    def set_persistence(self, depth: int | None) -> None:
        """Fade over ``depth`` acquisitions; None = infinite, 0 = off."""
        if depth == 0:
            self.persistence = None
            self._persistence_timer.stop()
            self.persistence_image.clear()
            self.persistence_image.setVisible(False)
            return
        if self.persistence is None:
            self.persistence = Persistence(depth=depth)
        else:
            self.persistence.set_depth(depth)
        self.persistence_image.setVisible(True)

    def _restart_persistence(self) -> None:
        """The bins no longer match the screen (view or scale changed, disconnected)."""
        if self.persistence is not None:
            self.persistence.reset()
            self._persistence_timer.stop()
            self.persistence_image.clear()

    def _add_persistence(self) -> None:
        if self.persistence is None or self._status is None:
            return
        vb = self.plot.vb
        width, height = int(vb.width()), int(vb.height())
        if width < 2 or height < 2:
            return
        (x0, x1), (y0, y1) = vb.viewRange()
        self.persistence.set_size(width, height)  # both reset the map only when they change
        self.persistence.set_view((x0, x1), (y0, y1))
        visible = {n: w for n, w in self._waveforms.items() if self.is_curve_visible(n)}
        self.persistence.add_waveforms(visible, self._status)
        if not self._persistence_timer.isActive():
            self._persistence_timer.start()

    def _paint_persistence(self) -> None:
        if self.persistence is None or self.persistence.view is None:
            return
        (x0, x1), (y0, y1) = self.persistence.view
        self.persistence_image.setImage(self.persistence.image(), autoLevels=False)
        self.persistence_image.setRect(x0, y0, x1 - x0, y1 - y0)

    @property
    def no_channels_visible(self) -> bool:
        return not self._no_channels.isHidden()

    @property
    def multigrid_note_visible(self) -> bool:
        return not self._multigrid.isHidden()

    @property
    def stale_visible(self) -> bool:
        return not self._stale_label.isHidden()

    # -- drawing ------------------------------------------------------------------------

    def _draw(self, name: str) -> None:
        waveform = self._waveforms.get(name)
        if waveform is None or self._status is None:
            return
        y = volts_to_div(waveform.volts, self._status.channel(name))
        self.curves[name].setData(self._times(waveform), y, skipFiniteCheck=True)

    def _times(self, waveform: Waveform) -> np.ndarray:
        """``waveform.times`` in one pass: i * dt is kept while the timebase stays the same."""
        key = (waveform.volts.size, waveform.dt)
        if key != self._ramp_key:
            self._ramp_key = key
            self._ramp = np.arange(key[0]) * key[1]
        return self._ramp + waveform.t0

    def _refresh_visibility(self) -> None:
        for name, curve in self.curves.items():
            curve.setVisible(self.is_curve_visible(name))

    def _update_range(self, status: ScopeStatus) -> None:
        acq = status.acquisition
        x_min, x_max = x_range(acq)
        if not self.zoomed:  # while zoomed the user owns the range; the grid still follows
            self.plot.setXRange(x_min, x_max, padding=0)
            self.plot.setYRange(*Y_RANGE_DIV, padding=0)
        key = (x_min, x_max, acq.h_divisions)
        if key == self._grid_x:
            return
        self._grid_x = key
        v_lines = x_min + np.arange(acq.h_divisions + 1) * acq.time_per_div
        h_lines = np.arange(Y_RANGE_DIV[0], Y_RANGE_DIV[1] + 1)
        x_centre = (x_min + x_max) / 2
        y_min, y_max = Y_RANGE_DIV

        v_lines = v_lines[~np.isclose(v_lines, x_centre, rtol=0, atol=acq.time_per_div * 1e-6)]
        h_lines = h_lines[h_lines != 0]
        self._grid.setData(*_line_pairs(v_lines, h_lines, x_min, x_max, y_min, y_max))
        self._grid_centre.setData(
            *_line_pairs(np.array([x_centre]), np.array([0.0]), x_min, x_max, y_min, y_max)
        )

    # -- overlays -----------------------------------------------------------------------

    def _layout_overlays(self) -> None:
        area = self.plot_widget.mapFromScene(self.plot.vb.sceneBoundingRect()).boundingRect()
        left, top, width, height = area.x(), area.y(), area.width(), area.height()
        m = OVERLAY_MARGIN

        overlays = (
            self._no_channels,
            self._multigrid,
            self._stale_label,
            self._hover,
            self._cursor_readout,
        )
        for label in overlays:
            label.adjustSize()
            label.raise_()
        self._no_channels.move(
            left + (width - self._no_channels.width()) // 2,
            top + (height - self._no_channels.height()) // 2,
        )
        self._multigrid.move(left + m, top + m)
        self._stale_label.move(left + width - self._stale_label.width() - m, top + m)
        self._hover.move(left + m, top + height - self._hover.height() - m)
        below_note = self._multigrid.height() + m if self.multigrid_note_visible else 0
        self._cursor_readout.move(left + m, top + m + below_note)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        kind = event.type()
        if obj is self.plot_widget and kind == QEvent.Type.Resize:
            self._layout_overlays()
        elif kind == QEvent.Type.Leave:
            self._hover.hide()
        return super().eventFilter(obj, event)

    # -- hover readout ------------------------------------------------------------------

    def _on_mouse_moved(self, args) -> None:
        pos = args[0]
        vb = self.plot.vb
        if not vb.sceneBoundingRect().contains(pos):
            self._hover.hide()
            return
        point = vb.mapSceneToView(pos)
        self.show_readout(point.x(), point.y())

    def show_readout(self, time: float, div: float) -> None:
        """Show time and per-channel volts for a cursor at (time, div) in view coordinates."""
        if self._status is None:
            self._hover.hide()
            return
        lines = [f"t = {pg.siFormat(time, suffix='s', precision=4)}"]
        for name in CHANNELS:
            if self.is_curve_visible(name):
                volts = div_to_volts(div, self._status.channel(name))
                text = pg.siFormat(volts, suffix="V", precision=4)
                lines.append(f'<span style="color: {CHANNEL_COLORS[name]}">{name} = {text}</span>')
        self._hover.setText("<br>".join(lines))
        self._hover.setVisible(True)
        self._layout_overlays()

    @property
    def hover_text(self) -> str:
        return "" if self._hover.isHidden() else self._hover.text()


def _line_pairs(
    xs: np.ndarray, ys: np.ndarray, x_min: float, x_max: float, y_min: float, y_max: float
) -> tuple[np.ndarray, np.ndarray]:
    """Vertical lines at xs spanning y, and horizontal lines at ys spanning x, as point pairs."""
    vx = np.repeat(xs, 2)
    vy = np.tile([y_min, y_max], xs.size)
    hx = np.tile([x_min, x_max], ys.size)
    hy = np.repeat(ys, 2)
    return np.concatenate([vx, hx]), np.concatenate([vy, hy])


def _value_at(waveform: Waveform, t: float) -> float:
    """The waveform's voltage at time t, interpolated between samples; NaN outside the record."""
    position = (t - waveform.t0) / waveform.dt
    if not 0 <= position <= waveform.volts.size - 1:
        return math.nan
    i = min(int(position), waveform.volts.size - 2)
    v0, v1 = float(waveform.volts[i]), float(waveform.volts[i + 1])
    return v0 + (position - i) * (v1 - v0)


def _scales(status: ScopeStatus):
    """What the persistence bins depend on: timebase and every channel's scale."""
    acq = status.acquisition
    return (
        acq.time_per_div,
        acq.trigger_delay,
        tuple((ch.volts_per_div, ch.offset, ch.enabled) for ch in status.channels),
    )
