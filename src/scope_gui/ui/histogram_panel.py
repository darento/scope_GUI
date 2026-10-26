"""Histogram, trend and correlation of the selected measurement (contracts/ui.md).

The panel only draws what ``Statistics`` already holds; it never touches the instrument. Call
``show_measurements`` after every processed acquisition and whenever the selection changes: it
recomputes only the view that is visible (a histogram of 100k values takes a few ms) and does
nothing while the panel is hidden (a closed dock); ``showEvent`` catches up.
"""

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..analysis import MeasurementSpec, RangeMode, Statistics, gauss_fit, histogram_range, si_format

BINS_MIN, BINS_MAX, BINS_DEFAULT = 10, 1000, 100
CORRELATION_POINTS = 5000  # latest acquisitions shown in the scatter plot
FIT_POINTS = 200

VIEWS = ("Histogram", "Trend", "Correlation")
BAR_COLOR = "#3fc8f0"
FIT_COLOR = "#ff9a1f"
TEXT_COLOR = "#d0d0d0"
INVALID_STYLE = "background: #5a1f1f;"


def format_value(value: float, unit: str) -> str:
    """4 significant digits with an SI prefix; % with 2 decimals; plain numbers for counts."""
    if not math.isfinite(value):
        return "—"
    if unit == "%":
        return f"{value:.2f} %"
    if unit == "":
        return f"{value:.4g}"
    return si_format(value, unit)


def _parse(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


class HistogramPanel(QWidget):
    """Controls above a plot above a one-line summary.

    Attributes meant for tests and wiring: ``view_combo``, ``x_combo``, ``bins_spin``,
    ``range_combo``, ``from_edit``, ``to_edit``, ``log_check``, ``fit_check``, ``plot``,
    ``hist_curve``, ``fit_curve``, ``trend_curve``, ``scatter``, ``stats_label``, ``fit``
    (the last ``GaussFit`` or None), ``view`` (name of the current view), ``is_log``.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._specs: list[MeasurementSpec] = []
        self._stats: list[Statistics] = []
        self._selected: int | None = None
        self._x_specs: tuple[MeasurementSpec, ...] = ()
        self._x_indices: list[int] = []  # index in the measurement list of each X combo entry
        self.fit = None
        self.outside = 0

        self.view_combo = QComboBox()
        self.view_combo.addItems(VIEWS)
        self.x_label = QLabel("X:")
        self.x_combo = QComboBox()
        self.x_combo.setMinimumContentsLength(16)
        self.bins_label = QLabel("Bins")
        self.bins_spin = QSpinBox()
        self.bins_spin.setRange(BINS_MIN, BINS_MAX)
        self.bins_spin.setValue(BINS_DEFAULT)
        self.range_label = QLabel("Range")
        self.range_combo = QComboBox()
        self.range_combo.addItems([mode.value for mode in RangeMode])
        self.from_edit = QLineEdit()
        self.from_edit.setPlaceholderText("from")
        self.to_edit = QLineEdit()
        self.to_edit.setPlaceholderText("to")
        for edit in (self.from_edit, self.to_edit):
            edit.setMaximumWidth(90)
            edit.setToolTip("Manual range in base units (V, s, Hz, …), e.g. 1.5e-9")
        self.log_check = QCheckBox("Log")
        self.fit_check = QCheckBox("Fit")
        self.fit_check.setChecked(True)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        for widget in (
            self.view_combo,
            self.x_label,
            self.x_combo,
            self.bins_label,
            self.bins_spin,
            self.range_label,
            self.range_combo,
            self.from_edit,
            self.to_edit,
            self.log_check,
            self.fit_check,
        ):
            controls.addWidget(widget)
        controls.addStretch(1)

        self.plot_widget = pg.PlotWidget(background="k")
        self.plot: pg.PlotItem = self.plot_widget.getPlotItem()
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.setMouseEnabled(False, False)
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.hist_curve = pg.PlotDataItem(
            stepMode="center", fillLevel=0, brush=pg.mkBrush(63, 200, 240, 70), pen=BAR_COLOR
        )
        self.fit_curve = pg.PlotDataItem(pen=pg.mkPen(FIT_COLOR, width=2))
        self.trend_curve = pg.PlotDataItem(pen=pg.mkPen(BAR_COLOR), connect="finite")
        self.trend_curve.setDownsampling(auto=True, method="peak")
        self.scatter = pg.ScatterPlotItem(size=3, pen=None, brush=pg.mkBrush(63, 200, 240, 110))
        for item in (self.hist_curve, self.fit_curve, self.trend_curve, self.scatter):
            self.plot.addItem(item)

        self.stats_label = QLabel()
        self.stats_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.stats_label.setStyleSheet(f"color: {TEXT_COLOR};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(controls)
        layout.addWidget(self.plot_widget, 1)
        layout.addWidget(self.stats_label)

        self.view_combo.currentIndexChanged.connect(self._on_controls_changed)
        self.x_combo.currentIndexChanged.connect(self._on_controls_changed)
        self.bins_spin.valueChanged.connect(self._on_controls_changed)
        self.range_combo.currentIndexChanged.connect(self._on_range_mode_changed)
        self.from_edit.textChanged.connect(self._on_controls_changed)
        self.to_edit.textChanged.connect(self._on_controls_changed)
        self.log_check.toggled.connect(self._on_controls_changed)
        self.fit_check.toggled.connect(self._on_controls_changed)
        self._update_control_visibility()
        self._draw()

    # --- state ---------------------------------------------------------------------------
    @property
    def view(self) -> str:
        return self.view_combo.currentText()

    @property
    def range_mode(self) -> RangeMode:
        return RangeMode(self.range_combo.currentText())

    @property
    def is_log(self) -> bool:
        return bool(self.plot.getAxis("left").logMode)

    @property
    def selected_x(self) -> MeasurementSpec | None:
        """The measurement on the X axis of the correlation view."""
        data = self.x_combo.currentData()
        return data if isinstance(data, MeasurementSpec) else None

    # --- entry point -----------------------------------------------------------------------
    def show_measurements(
        self,
        specs: list[MeasurementSpec],
        stats: list[Statistics],
        selected: int | None,
    ) -> None:
        """Show the measurement ``specs[selected]``; ``stats[i]`` holds the values of ``specs[i]``.

        The lists are read, not copied: call again after the statistics changed. Only the
        current view is recomputed, and nothing while the panel is hidden.
        """
        self._specs, self._stats = list(specs), list(stats)
        valid = selected is not None and 0 <= selected < len(specs)
        self._selected = selected if valid else None
        self._update_x_choices()
        if self.isVisible():
            self._draw()

    def refresh(self) -> None:
        self._draw()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._draw()

    # --- controls ----------------------------------------------------------------------------
    def _update_x_choices(self) -> None:
        """X measurement choices: every measurement except the selected one."""
        self._x_indices = [i for i in range(len(self._specs)) if i != self._selected]
        others = tuple(self._specs[i] for i in self._x_indices)
        if others == self._x_specs:
            return
        current = self.selected_x
        self._x_specs = others
        self.x_combo.blockSignals(True)
        self.x_combo.clear()
        for spec in others:
            self.x_combo.addItem(spec.name, spec)
        if current in others:
            self.x_combo.setCurrentIndex(others.index(current))
        self.x_combo.blockSignals(False)

    def _update_control_visibility(self) -> None:
        view = self.view
        for widget in (self.x_label, self.x_combo):
            widget.setVisible(view == "Correlation")
        histogram = view == "Histogram"
        manual = histogram and self.range_mode is RangeMode.MANUAL
        for widget in (self.bins_label, self.bins_spin, self.range_label, self.range_combo):
            widget.setVisible(histogram)
        for widget in (self.from_edit, self.to_edit):
            widget.setVisible(manual)
        self.log_check.setVisible(histogram)
        self.fit_check.setVisible(histogram)

    def _on_controls_changed(self, *_) -> None:
        self._update_control_visibility()
        if self.isVisible():
            self._draw()

    def _on_range_mode_changed(self, *_) -> None:
        if self.range_mode is RangeMode.MANUAL and not (
            self.from_edit.text() or self.to_edit.text()
        ):
            low, high = self._auto_range()  # start from what is on screen
            for edit, value in ((self.from_edit, low), (self.to_edit, high)):
                edit.blockSignals(True)
                edit.setText(f"{value:.6g}")
                edit.blockSignals(False)
        self._on_controls_changed()

    def _auto_range(self) -> tuple[float, float]:
        values = self._values(self._selected)
        return histogram_range(values, RangeMode.AUTO_ROBUST)

    def _manual_range(self) -> tuple[float, float] | None:
        low, high = _parse(self.from_edit.text()), _parse(self.to_edit.text())
        for edit, value in ((self.from_edit, low), (self.to_edit, high)):
            edit.setStyleSheet("" if value is not None else INVALID_STYLE)
        if low is None or high is None:
            return None
        return low, high

    # --- data ----------------------------------------------------------------------------
    def _values(self, index: int | None) -> np.ndarray:
        if index is None or index >= len(self._stats):
            return np.empty(0)
        return self._stats[index].values()

    def _history(self, index: int | None) -> np.ndarray:
        if index is None or index >= len(self._stats):
            return np.empty(0)
        return self._stats[index].history()

    # --- drawing -----------------------------------------------------------------------------
    def _draw(self) -> None:
        selected = self._selected
        self._hide_items()
        self.fit = None
        self.outside = 0
        if selected is None:
            self.plot.setTitle("")
            self.stats_label.setText("No measurement selected")
            return
        spec = self._specs[selected]
        view = self.view
        if view == "Histogram":
            self._draw_histogram(spec)
        elif view == "Trend":
            self._draw_trend(spec)
        else:
            self._draw_correlation(spec)

    def _hide_items(self) -> None:
        for item in (self.hist_curve, self.fit_curve, self.trend_curve, self.scatter):
            item.setVisible(False)

    def _set_axis(self, side: str, spec: MeasurementSpec | None, text: str = "") -> None:
        axis = self.plot.getAxis(side)
        if spec is None:
            self.plot.setLabel(side, text, units="")
            axis.enableAutoSIPrefix(True)
            return
        unit = spec.kind.unit
        self.plot.setLabel(side, spec.name, units=unit)
        axis.enableAutoSIPrefix(unit not in ("", "%"))

    def _draw_histogram(self, spec: MeasurementSpec) -> None:
        values = self._values(self._selected)
        self.plot.setTitle(spec.name)
        self._set_axis("bottom", spec)
        self._set_axis("left", None, "Counts")
        self.plot.setLogMode(False, self.log_check.isChecked())
        mode = self.range_mode
        manual = self._manual_range() if mode is RangeMode.MANUAL else None
        low, high = histogram_range(values, mode, manual)
        if mode is RangeMode.MANUAL and manual is None:  # fields not valid (yet): show everything
            low, high = histogram_range(values, RangeMode.AUTO_ROBUST)
        inside = values[(values >= low) & (values <= high)]
        self.outside = int(values.size - inside.size)
        counts, edges = np.histogram(inside, self.bins_spin.value(), (low, high))
        self.hist_curve.setData(edges, counts)
        self.hist_curve.setVisible(True)
        parts = [f"N {inside.size}", f"outside {self.outside}"]
        if inside.size:
            parts.append(f"mean {format_value(float(inside.mean()), spec.kind.unit)}")
            sigma = float(inside.std(ddof=1)) if inside.size > 1 else 0.0
            parts.append(f"σ {format_value(sigma, spec.kind.unit)}")
        if self.fit_check.isChecked():
            centers = (edges[:-1] + edges[1:]) / 2
            self.fit = gauss_fit(centers, counts)
            if self.fit is None:
                parts.append("no fit")
            else:
                unit = spec.kind.unit
                fit = self.fit
                parts.append(
                    f"fit μ {format_value(fit.mean, unit)} σ {format_value(fit.sigma, unit)}"
                    f" FWHM {format_value(fit.fwhm, unit)}"
                )
                x = np.linspace(low, high, FIT_POINTS)
                self.fit_curve.setData(x, fit(x))
                self.fit_curve.setVisible(True)
        self.stats_label.setText(" · ".join(parts))
        self.plot.enableAutoRange()

    def _draw_trend(self, spec: MeasurementSpec) -> None:
        history = self._history(self._selected)
        self.plot.setTitle(spec.name)
        self.plot.setLogMode(False, False)
        self.plot.setLabel("bottom", "Acquisition", units="")
        self.plot.getAxis("bottom").enableAutoSIPrefix(False)
        self._set_axis("left", spec)
        self.trend_curve.setData(np.arange(history.size), history)
        self.trend_curve.setVisible(True)
        finite = int(np.isfinite(history).sum())
        self.stats_label.setText(f"N {finite} · missed {history.size - finite}")
        self.plot.enableAutoRange()

    def _draw_correlation(self, spec: MeasurementSpec) -> None:
        x_spec = self.selected_x
        self.plot.setTitle(spec.name)
        self.plot.setLogMode(False, False)
        self._set_axis("left", spec)
        if x_spec is None:
            self._set_axis("bottom", None, "")
            self.stats_label.setText("Add a second measurement to see a correlation")
            return
        self._set_axis("bottom", x_spec)
        x_index = self._x_indices[self.x_combo.currentIndex()]
        x_all, y_all = self._history(x_index), self._history(self._selected)
        n = min(x_all.size, y_all.size)  # histories end at the latest acquisition: align there
        x_all, y_all = x_all[x_all.size - n :], y_all[y_all.size - n :]
        both = np.flatnonzero(np.isfinite(x_all) & np.isfinite(y_all))[-CORRELATION_POINTS:]
        x, y = x_all[both], y_all[both]
        self.scatter.setData(x, y)
        self.scatter.setVisible(True)
        text = f"N {x.size}"
        if x.size > 2 and x.std() > 0 and y.std() > 0:
            text += f" · correlation {np.corrcoef(x, y)[0, 1]:.3f}"
        self.stats_label.setText(text)
        self.plot.enableAutoRange()
