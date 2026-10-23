"""Plot mirroring the scope's screen: 10 x 8 divisions, scope trace colours (research R6, R7)."""

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

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

pg.setConfigOptions(antialias=False)

STALE_OPACITY = 0.4
GRID_COLOR = "#3c3c3c"
GRID_CENTRE_COLOR = "#6a6a6a"
TRIGGER_COLOR = "#ff9a1f"
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
    def __init__(self, parent=None):
        super().__init__(parent)
        self._status: ScopeStatus | None = None
        self._waveforms: dict[str, Waveform] = {}
        self._hidden: set[str] = set()
        self._stale = False
        self._grid_x: tuple[float, float, float] | None = None

        self.plot_widget = pg.PlotWidget(background="k")
        self.plot: pg.PlotItem = self.plot_widget.getPlotItem()
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.setMouseEnabled(False, False)
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
            curve.setDownsampling(auto=True, method="peak")
            curve.setClipToView(True)
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
        self._status = None
        self._waveforms.clear()
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
        self.curves[name].setData(waveform.times, y, skipFiniteCheck=True)

    def _refresh_visibility(self) -> None:
        for name, curve in self.curves.items():
            curve.setVisible(self.is_curve_visible(name))

    def _update_range(self, status: ScopeStatus) -> None:
        acq = status.acquisition
        x_min, x_max = x_range(acq)
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

        for label in (self._no_channels, self._multigrid, self._stale_label, self._hover):
            label.adjustSize()
            label.raise_()
        self._no_channels.move(
            left + (width - self._no_channels.width()) // 2,
            top + (height - self._no_channels.height()) // 2,
        )
        self._multigrid.move(left + m, top + m)
        self._stale_label.move(left + width - self._stale_label.width() - m, top + m)
        self._hover.move(left + m, top + height - self._hover.height() - m)

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
