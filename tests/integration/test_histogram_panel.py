"""Histogram, trend and correlation views fed with ``Statistics`` directly (contracts/ui.md)."""

import math
import time

import numpy as np
import pytest

from scope_gui.analysis import Edge, Kind, Level, MeasurementSpec, RangeMode, Statistics
from scope_gui.ui.histogram_panel import (
    BINS_MAX,
    BINS_MIN,
    CORRELATION_POINTS,
    HistogramPanel,
    format_value,
)

DELTA_T = MeasurementSpec(
    Kind.DELTA_T, "C2", Level(0.2, True, Edge.RISING), "C3", Level(0.2, True, Edge.RISING)
)
AMPLITUDE = MeasurementSpec(Kind.AMPLITUDE, "C2")
FREQUENCY = MeasurementSpec(Kind.FREQUENCY, "C1")
DUTY = MeasurementSpec(Kind.DUTY_CYCLE, "C1")


def stats_of(values) -> Statistics:
    stats = Statistics()
    for value in values:
        stats.add(float(value))
    return stats


@pytest.fixture
def panel(qtbot):
    widget = HistogramPanel()
    qtbot.addWidget(widget)
    widget.resize(900, 500)
    widget.show()
    return widget


def gaussian(n=2000, mean=2e-9, sigma=0.12e-9, seed=1):
    return np.random.default_rng(seed).normal(mean, sigma, n)


def show(panel, values_by_spec, selected=0):
    specs = list(values_by_spec)
    panel.show_measurements(specs, [stats_of(v) for v in values_by_spec.values()], selected)
    return specs


def edges(panel) -> np.ndarray:
    return np.asarray(panel.hist_curve.xData)


def counts(panel) -> np.ndarray:
    return np.asarray(panel.hist_curve.yData)


# --- histogram view ------------------------------------------------------------------------
def test_empty_panel_has_no_measurement(panel):
    assert panel.stats_label.text() == "No measurement selected"
    assert not panel.hist_curve.isVisible()
    panel.show_measurements([DELTA_T], [Statistics()], None)
    assert panel.stats_label.text() == "No measurement selected"


def test_title_and_axis_label_are_the_measurement_name_with_unit(panel):
    show(panel, {DELTA_T: gaussian()})
    assert panel.plot.titleLabel.text == DELTA_T.name
    axis = panel.plot.getAxis("bottom")
    assert (axis.labelText, axis.labelUnits) == (DELTA_T.name, "s")
    assert axis.autoSIPrefix  # the time axis reads in ns
    assert panel.plot.getAxis("left").labelText == "Counts"
    show(panel, {FREQUENCY: [1e7] * 20 + [1.01e7] * 5})
    assert panel.plot.getAxis("bottom").labelUnits == "Hz"
    show(panel, {DUTY: [49.5, 50.0, 50.5] * 10})
    axis = panel.plot.getAxis("bottom")
    assert axis.labelUnits == "%" and not axis.autoSIPrefix


def test_stats_line_shows_n_outside_mean_and_sigma(panel):
    values = np.concatenate([gaussian(1000), np.full(20, 150e-9)])  # 20 dark-count outliers
    show(panel, {DELTA_T: values})
    text = panel.stats_label.text()
    assert panel.outside == 20
    assert "outside 20" in text
    assert "N 1000" in text
    assert "mean 1.99" in text and " ns" in text  # about 2 ns
    assert "σ 1" in text and " ps" in text  # about 120 ps
    assert counts(panel).sum() == 1000


def test_fit_is_drawn_and_summarised(panel):
    show(panel, {DELTA_T: gaussian(5000)})
    assert panel.fit is not None
    assert panel.fit.mean == pytest.approx(2e-9, abs=10e-12)
    assert panel.fit.sigma == pytest.approx(0.12e-9, rel=0.05)
    assert panel.fit_curve.isVisible()
    text = panel.stats_label.text()
    assert "fit μ" in text and "FWHM" in text and "no fit" not in text
    panel.fit_check.setChecked(False)
    assert not panel.fit_curve.isVisible()
    assert "fit" not in panel.stats_label.text()
    panel.fit_check.setChecked(True)
    assert panel.fit_curve.isVisible()


def test_flat_or_scarce_data_has_no_fit(panel):
    show(panel, {AMPLITUDE: np.repeat(np.linspace(0.0, 1.0, 100), 5)})  # every bin equal
    assert panel.fit is None
    assert "no fit" in panel.stats_label.text()
    assert not panel.fit_curve.isVisible()
    show(panel, {AMPLITUDE: [0.1, 0.2, 0.2]})
    assert "no fit" in panel.stats_label.text()


def test_bins_are_limited_to_10_to_1000(panel):
    show(panel, {DELTA_T: gaussian()})
    assert panel.bins_spin.value() == 100
    assert counts(panel).size == 100
    panel.bins_spin.setValue(3)
    assert panel.bins_spin.value() == BINS_MIN == 10
    assert counts(panel).size == 10
    panel.bins_spin.setValue(5000)
    assert panel.bins_spin.value() == BINS_MAX == 1000
    assert counts(panel).size == 1000


def test_log_toggles_the_count_axis(panel):
    show(panel, {DELTA_T: gaussian()})
    assert not panel.is_log
    panel.log_check.setChecked(True)
    assert panel.is_log
    panel.log_check.setChecked(False)
    assert not panel.is_log


def test_auto_range_ignores_outliers_full_range_shows_them(panel):
    values = np.concatenate([gaussian(1000), np.full(300, 100e-9)])
    show(panel, {DELTA_T: values})
    assert edges(panel)[-1] < 10e-9 and panel.outside == 300
    panel.range_combo.setCurrentText(RangeMode.FULL.value)
    assert edges(panel)[-1] == pytest.approx(100e-9)
    assert panel.outside == 0
    assert "N 1300" in panel.stats_label.text()


def test_manual_range_shows_fields_and_is_applied(panel):
    values = gaussian(1000)
    show(panel, {DELTA_T: values})
    assert not panel.from_edit.isVisible()
    panel.range_combo.setCurrentText(RangeMode.MANUAL.value)
    assert panel.from_edit.isVisible() and panel.to_edit.isVisible()
    assert panel.from_edit.text() and panel.to_edit.text()  # prefilled with the current range
    panel.from_edit.setText("1.9e-9")
    panel.to_edit.setText("2.1e-9")
    assert edges(panel)[0] == pytest.approx(1.9e-9)
    assert edges(panel)[-1] == pytest.approx(2.1e-9)
    inside = ((values >= 1.9e-9) & (values <= 2.1e-9)).sum()
    assert panel.outside == values.size - inside
    assert counts(panel).sum() == inside
    panel.range_combo.setCurrentText(RangeMode.AUTO_ROBUST.value)
    assert not panel.from_edit.isVisible()


def test_invalid_manual_range_falls_back_to_auto(panel):
    show(panel, {DELTA_T: gaussian()})
    panel.range_combo.setCurrentText(RangeMode.MANUAL.value)
    panel.from_edit.setText("abc")
    assert counts(panel).size == 100  # still drawn
    assert panel.from_edit.styleSheet()  # marked invalid
    panel.from_edit.setText("1.9e-9")
    assert not panel.from_edit.styleSheet()


def test_selecting_another_measurement_switches_the_histogram(panel):
    data = {DELTA_T: gaussian(), AMPLITUDE: np.random.default_rng(2).normal(0.06, 0.004, 1500)}
    specs = show(panel, data, selected=0)
    assert panel.plot.titleLabel.text == DELTA_T.name
    panel.show_measurements(specs, [stats_of(v) for v in data.values()], 1)
    assert panel.plot.titleLabel.text == AMPLITUDE.name
    assert panel.plot.getAxis("bottom").labelUnits == "V"
    assert edges(panel)[0] > 0.04  # volts now, not nanoseconds


def test_values_are_read_again_on_each_call(panel):
    stats = stats_of(gaussian(500))
    panel.show_measurements([DELTA_T], [stats], 0)
    assert "N 500" in panel.stats_label.text()
    for value in gaussian(100, seed=9):
        stats.add(float(value))
    panel.show_measurements([DELTA_T], [stats], 0)
    assert "N 600" in panel.stats_label.text()
    stats.clear()
    panel.show_measurements([DELTA_T], [stats], 0)
    assert "N 0" in panel.stats_label.text()


def test_nothing_is_drawn_while_hidden_and_it_catches_up_when_shown(qtbot):
    widget = HistogramPanel()
    qtbot.addWidget(widget)
    widget.show_measurements([DELTA_T], [stats_of(gaussian())], 0)
    assert widget.hist_curve.xData is None  # hidden: no work
    widget.show()
    assert counts(widget).size == 100


# --- trend view ----------------------------------------------------------------------------
def test_trend_shows_values_against_acquisition_with_gaps(panel):
    values = gaussian(300)
    values[[10, 11, 200]] = math.nan
    show(panel, {DELTA_T: values})
    panel.view_combo.setCurrentText("Trend")
    assert panel.trend_curve.isVisible() and not panel.hist_curve.isVisible()
    assert not panel.bins_spin.isVisible() and not panel.log_check.isVisible()
    assert panel.trend_curve.opts["connect"] == "finite"
    x, y = np.asarray(panel.trend_curve.xData), np.asarray(panel.trend_curve.yData)
    assert x.tolist() == list(range(300))
    assert np.isnan(y[[10, 11, 200]]).all() and np.isfinite(y).sum() == 297
    assert "missed 3" in panel.stats_label.text()
    assert panel.plot.getAxis("bottom").labelText == "Acquisition"
    assert panel.plot.getAxis("left").labelText == DELTA_T.name
    panel.view_combo.setCurrentText("Histogram")
    assert panel.hist_curve.isVisible() and not panel.trend_curve.isVisible()


# --- correlation view ----------------------------------------------------------------------
def correlation_data(n=300):
    rng = np.random.default_rng(4)
    amplitude = rng.normal(0.06, 0.01, n)
    delta_t = 2e-9 - 5e-9 * (amplitude - 0.06) + rng.normal(0, 0.02e-9, n)
    return delta_t, amplitude


def test_correlation_plots_only_acquisitions_where_both_exist(panel):
    delta_t, amplitude = correlation_data()
    delta_t[5], amplitude[7] = math.nan, math.nan
    show(panel, {DELTA_T: delta_t, AMPLITUDE: amplitude, FREQUENCY: np.full(300, 1e7)}, 0)
    panel.view_combo.setCurrentText("Correlation")
    assert panel.x_combo.isVisible()
    assert [panel.x_combo.itemText(i) for i in range(panel.x_combo.count())] == [
        AMPLITUDE.name,
        FREQUENCY.name,
    ]
    assert panel.selected_x == AMPLITUDE  # default: the first other measurement
    x, y = panel.scatter.getData()
    keep = np.isfinite(delta_t) & np.isfinite(amplitude)
    assert x.size == y.size == 298
    np.testing.assert_allclose(x, amplitude[keep])  # X = the chosen measurement
    np.testing.assert_allclose(y, delta_t[keep])  # Y = the selected one
    assert panel.plot.getAxis("bottom").labelText == AMPLITUDE.name
    assert panel.plot.getAxis("left").labelText == DELTA_T.name
    assert "correlation -0.9" in panel.stats_label.text()
    panel.x_combo.setCurrentIndex(1)
    assert panel.selected_x == FREQUENCY
    assert panel.plot.getAxis("bottom").labelUnits == "Hz"
    assert np.allclose(panel.scatter.getData()[0], 1e7)


def test_correlation_keeps_the_latest_5000_points(panel):
    n = 7000
    show(panel, {DELTA_T: np.arange(n, dtype=float), AMPLITUDE: np.arange(n) * 2.0})
    panel.view_combo.setCurrentText("Correlation")
    x, y = panel.scatter.getData()
    assert x.size == CORRELATION_POINTS == 5000
    assert y[-1] == n - 1 and y[0] == n - 5000  # the newest acquisitions
    assert x[-1] == 2.0 * (n - 1)


def test_correlation_aligns_histories_of_different_length_at_the_latest_acquisition(panel):
    # AMPLITUDE was cleared (edited) after 60 acquisitions: it holds only the last 40.
    show(panel, {DELTA_T: np.arange(100.0), AMPLITUDE: np.arange(60.0, 100.0) * 10})
    panel.view_combo.setCurrentText("Correlation")
    x, y = panel.scatter.getData()
    assert y.tolist() == list(np.arange(60.0, 100.0))
    assert x.tolist() == list(np.arange(60.0, 100.0) * 10)


def test_correlation_with_a_single_measurement_says_so(panel):
    show(panel, {DELTA_T: gaussian()})
    panel.view_combo.setCurrentText("Correlation")
    assert panel.selected_x is None
    assert "second measurement" in panel.stats_label.text()
    assert not panel.scatter.isVisible()


def test_x_choice_survives_adding_a_measurement(panel):
    data = {DELTA_T: gaussian(100), AMPLITUDE: gaussian(100), FREQUENCY: np.full(100, 1e7)}
    show(panel, data, 0)
    panel.x_combo.setCurrentIndex(1)
    assert panel.selected_x == FREQUENCY
    data[DUTY] = np.full(100, 50.0)
    show(panel, data, 0)
    assert panel.selected_x == FREQUENCY


# --- formatting and cost -------------------------------------------------------------------
def test_value_formatting():
    assert format_value(2.0e-9, "s") == "2 ns"
    assert format_value(0.0605, "V") == "60.5 mV"
    assert format_value(49.5, "%") == "49.50 %"
    assert format_value(3.0, "") == "3"
    assert format_value(math.nan, "V") == "—"


def test_redraw_with_full_histories_is_cheap(panel):
    rng = np.random.default_rng(6)
    n = 100_000
    data = {DELTA_T: rng.normal(2e-9, 0.12e-9, n), AMPLITUDE: rng.normal(0.06, 0.01, n)}
    specs = list(data)
    stats = [stats_of(v) for v in data.values()]
    for view in ("Histogram", "Trend", "Correlation"):
        panel.view_combo.setCurrentText(view)
        start = time.perf_counter()
        for _ in range(5):
            panel.show_measurements(specs, stats, 0)
        per_call = (time.perf_counter() - start) / 5
        assert per_call < 0.1, f"{view}: {per_call * 1000:.0f} ms per redraw"
