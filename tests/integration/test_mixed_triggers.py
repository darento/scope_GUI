"""Mixed-trigger updates: cross-channel measurements and correlations (003 FR-015, R10)."""

import math

import numpy as np
import pytest

from scope_gui.analysis import Kind, Level, MeasurementSpec, Statistics
from scope_gui.models import Waveform
from scope_gui.ui.histogram_panel import HistogramPanel
from scope_gui.ui.measurements_panel import MeasurementsPanel

DT = 1e-9
PERIOD = 20  # samples


def acquisition(amplitude: float = 1.0, triggers=(1.0, 1.0)):
    """C1 and C2: sines of 10 periods, C2 a quarter period later; trigger time of each."""
    k = np.arange(200)
    c1 = amplitude * np.sin(2 * np.pi * k / PERIOD)
    c2 = amplitude * np.sin(2 * np.pi * (k - PERIOD / 4) / PERIOD)
    return {
        "C1": Waveform("C1", c1.astype(np.float32), 0.0, DT, triggers[0], 0),
        "C2": Waveform("C2", c2.astype(np.float32), 0.0, DT, triggers[1], 0),
    }


RISING = Level(0.1)
DT_C1_C2 = MeasurementSpec(Kind.DELTA_T, "C1", RISING, "C2", RISING)
DT_C2_C2 = MeasurementSpec(Kind.DELTA_T, "C2", RISING, "C2", Level(0.5))
AMP_C1 = MeasurementSpec(Kind.AMPLITUDE, "C1")
AMP_C2 = MeasurementSpec(Kind.AMPLITUDE, "C2")
FREQ_C1 = MeasurementSpec(Kind.FREQUENCY, "C1")


@pytest.fixture
def panel(qtbot):
    widget = MeasurementsPanel()
    qtbot.addWidget(widget)
    while widget.specs:  # start without the remembered measurements
        widget.remove(0)
    return widget


def with_specs(panel, *specs):
    for spec in specs:
        panel.add(spec)


def last(panel, row: int) -> float:
    return panel.stats[row].last


# --- measurements ------------------------------------------------------------------------------
def test_coherent_update_measures_everything(panel):
    with_specs(panel, DT_C1_C2, DT_C2_C2, AMP_C1, FREQ_C1)
    panel.process(acquisition(), coherent=True)
    assert [panel.stats[i].summary().count for i in range(4)] == [1, 1, 1, 1]
    assert math.isfinite(last(panel, 0))
    assert panel.coherence_log.history().tolist() == [1.0]


def test_default_is_coherent(panel):
    with_specs(panel, DT_C1_C2)
    panel.process(acquisition(triggers=(1.0, 2.0)))
    assert panel.stats[0].summary().count == 1


def test_mixed_update_misses_only_cross_channel_measurements(panel):
    with_specs(panel, DT_C1_C2, DT_C2_C2, AMP_C1, FREQ_C1)
    panel.process(acquisition(triggers=(1.0, 2.0)), coherent=False)
    assert math.isnan(last(panel, 0))
    assert panel.stats[0].summary().missed == 1
    # Δt of one channel with itself, and single-channel ones, are measured as usual
    for row in (1, 2, 3):
        assert math.isfinite(last(panel, row)), row
        assert panel.stats[row].summary().missed == 0
    assert panel.coherence_log.history().tolist() == [0.0]


def test_mixed_update_keeps_one_entry_per_measurement(panel):
    with_specs(panel, DT_C1_C2, AMP_C1)
    panel.process(acquisition(), coherent=True)
    panel.process(acquisition(), coherent=False)
    panel.process(acquisition(), coherent=True)
    assert [s.size for s in panel.stats] == [3, 3]
    assert panel.trigger_log.size == panel.coherence_log.size == 3
    assert np.isnan(panel.stats[0].history()[1])
    assert panel.stats[0].summary().count == 2
    assert panel.cell_text(0, "Missed") == "1"
    assert panel.cell_text(1, "Missed") == "0"


def test_coherence_log_is_aligned_with_the_trigger_log(panel):
    with_specs(panel, AMP_C1)
    flags = [True, False, False, True, True]
    for i, coherent in enumerate(flags):
        panel.process(acquisition(triggers=(float(i), float(i))), coherent=coherent)
    assert panel.trigger_log.history().tolist() == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert panel.coherence_log.history().tolist() == [1.0, 0.0, 0.0, 1.0, 1.0]


def test_coherence_log_wraps_like_the_trigger_log(panel):
    panel.coherence_log = Statistics(4)  # same ring buffer as the real one, a small capacity
    panel.trigger_log = Statistics(4)
    with_specs(panel, AMP_C1)
    for i in range(7):
        panel.process(
            acquisition(triggers=(float(i), float(i))), coherent=i % 3 != 0
        )  # mixed at 0, 3, 6
    assert panel.trigger_log.history().tolist() == [3.0, 4.0, 5.0, 6.0]
    assert panel.coherence_log.history().tolist() == [0.0, 1.0, 1.0, 0.0]


def test_clear_empties_the_coherence_log(panel):
    with_specs(panel, DT_C1_C2)
    panel.process(acquisition(), coherent=False)
    panel.clear_button.click()
    assert panel.coherence_log.size == panel.trigger_log.size == 0
    panel.process(acquisition(), coherent=True)
    assert panel.coherence_log.history().tolist() == [1.0]


# --- correlation -------------------------------------------------------------------------------
@pytest.fixture
def histogram(qtbot):
    widget = HistogramPanel()
    qtbot.addWidget(widget)
    widget.resize(900, 500)
    widget.show()
    widget.view_combo.setCurrentText("Correlation")
    return widget


def correlate(panel, histogram, y: MeasurementSpec, x: MeasurementSpec, flags, *, log=True):
    """Process one acquisition per flag (amplitude grows), then show y against x."""
    with_specs(panel, y, x)
    for i, coherent in enumerate(flags):
        panel.process(acquisition(1.0 + i / 10), coherent=coherent)
    histogram.show_measurements(panel.specs, panel.stats, 0, panel.coherence_log if log else None)
    histogram.x_combo.setCurrentIndex(0)
    histogram.refresh()
    return len(histogram.scatter.getData()[0]), histogram.stats_label.text()


MIXED = [True, False, True, True, False, True]  # 4 coherent, 2 mixed


def test_correlation_of_two_cross_channel_measurements_drops_mixed_pairs(panel, histogram):
    n, text = correlate(panel, histogram, AMP_C1, AMP_C2, MIXED)
    assert n == 4 and text.startswith("N 4")


def test_correlation_of_cross_channel_delta_t_with_a_channel_drops_mixed_pairs(panel, histogram):
    n, text = correlate(panel, histogram, DT_C1_C2, AMP_C1, MIXED)
    assert n == 4 and text.startswith("N 4")


def test_correlation_within_one_channel_keeps_mixed_pairs(panel, histogram):
    n, text = correlate(panel, histogram, AMP_C1, FREQ_C1, MIXED)
    assert n == 6 and text.startswith("N 6")


def test_correlation_without_coherence_log_keeps_everything(panel, histogram):
    n, _ = correlate(panel, histogram, AMP_C1, AMP_C2, MIXED, log=False)
    assert n == 6


def test_correlation_aligns_the_coherence_log_with_a_younger_measurement(panel, histogram):
    with_specs(panel, AMP_C1)
    panel.process(acquisition(), coherent=False)
    panel.process(acquisition(), coherent=True)
    with_specs(panel, AMP_C2)  # added later: its history is shorter than the log
    panel.process(acquisition(), coherent=False)
    panel.process(acquisition(), coherent=True)
    histogram.show_measurements(panel.specs, panel.stats, 0, panel.coherence_log)
    histogram.refresh()
    assert len(histogram.scatter.getData()[0]) == 1  # only the last acquisition is coherent


# --- window (T018) -----------------------------------------------------------------------------
