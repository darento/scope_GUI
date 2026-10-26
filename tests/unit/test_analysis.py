"""Behavioural guarantees of scope_gui.analysis (002 contracts/analysis.md)."""

import math

import numpy as np
import pytest

from scope_gui.analysis import (
    Edge,
    Kind,
    Level,
    MeasurementSpec,
    RangeMode,
    Statistics,
    crossing_indices,
    gauss_fit,
    histogram_range,
    measure_all,
    reference_levels,
)
from scope_gui.models import Waveform

# --- helpers -------------------------------------------------------------------------------------


def wf(volts, dt=1e-10, t0=0.0, name="C1", step=0.0) -> Waveform:
    return Waveform(name, np.asarray(volts, dtype=np.float32), t0, dt, 0.0, 0.0, step)


def times(n: int, dt: float, t0: float = 0.0) -> np.ndarray:
    return t0 + np.arange(n) * dt


def edge(t, at: float, rise: float) -> np.ndarray:
    """0 -> 1 step at ``at`` with a 10-90 % time of ``rise``."""
    return 0.5 * (1 + np.tanh((t - at) * (2 * math.atanh(0.8) / rise)))


def pulse(t, at: float, amplitude: float, rise: float = 1e-9, decay: float = 30e-9) -> np.ndarray:
    """Double-exponential pulse starting at ``at`` with peak ``amplitude``."""
    peak_t = rise * decay / (decay - rise) * math.log(decay / rise)
    norm = math.exp(-peak_t / decay) - math.exp(-peak_t / rise)
    s = np.clip(t - at, 0, None)
    return amplitude / norm * (np.exp(-s / decay) - np.exp(-s / rise))


def one(spec: MeasurementSpec, *waveforms: Waveform, gate=None) -> float:
    return measure_all([spec], {w.channel: w for w in waveforms}, gate)[0]


V = Level  # volts level
REL = Edge.RISING


def rel(fraction: float, edge_: Edge = Edge.RISING) -> Level:
    return Level(fraction, True, edge_)


# --- vocabulary (guarantee 13) -------------------------------------------------------------------

UNITS_AND_LEVELS = {
    Kind.DELTA_T: ("s", 2),
    Kind.TIME_AT_LEVEL: ("s", 1),
    Kind.EDGE_COUNT: ("", 1),
    Kind.AMPLITUDE: ("V", 0),
    Kind.BASE: ("V", 0),
    Kind.TOP: ("V", 0),
    Kind.MAXIMUM: ("V", 0),
    Kind.MINIMUM: ("V", 0),
    Kind.PK_PK: ("V", 0),
    Kind.MEAN: ("V", 0),
    Kind.AREA: ("V·s", 0),
    Kind.RISE_TIME: ("s", 0),
    Kind.FALL_TIME: ("s", 0),
    Kind.WIDTH: ("s", 0),
    Kind.PERIOD: ("s", 0),
    Kind.FREQUENCY: ("Hz", 0),
    Kind.DUTY_CYCLE: ("%", 0),
}


def test_every_kind_has_unit_and_level_count():
    assert set(UNITS_AND_LEVELS) == set(Kind)
    for kind, (unit, levels) in UNITS_AND_LEVELS.items():
        assert (kind.unit, kind.levels) == (unit, levels), kind


@pytest.mark.parametrize(
    "level,label",
    [
        (Level(0.030), "↑ 30 mV"),
        (Level(-0.4, edge=Edge.FALLING), "↓ -400 mV"),
        (Level(1.25), "↑ 1.25 V"),
        (rel(0.2), "lead 20%"),
        (rel(0.5, Edge.FALLING), "trail 50%"),
    ],
)
def test_level_labels(level, label):
    assert level.label() == label


def test_names():
    dt = MeasurementSpec(Kind.DELTA_T, "C2", Level(0.030), "C4", Level(-0.4, edge=Edge.FALLING))
    assert dt.name == "Δt C2 ↑ 30 mV → C4 ↓ -400 mV"
    assert MeasurementSpec(Kind.AMPLITUDE, "C2").name == "Amplitude C2"
    assert MeasurementSpec(Kind.TIME_AT_LEVEL, "C1", rel(0.5)).name == "Time C1 lead 50%"
    cfd = MeasurementSpec(Kind.DELTA_T, "C2", rel(0.2), "C3", rel(0.2))
    assert cfd.name == "Δt C2 lead 20% → C3 lead 20%"


@pytest.mark.parametrize("kind", list(Kind))
def test_spec_round_trip(kind):
    spec = MeasurementSpec(kind, "C3", rel(0.35, Edge.FALLING), "C1", Level(-0.02))
    data = spec.to_dict()
    assert data["kind"] == kind.name  # enum names are stored, not labels
    assert data["level"]["edge"] == "FALLING"
    assert MeasurementSpec.from_dict(data) == spec


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "NOT_A_KIND"},
        {"source": "C9"},
        {"source2": "F1"},
        {"level": {"value": 0.1, "relative": False, "edge": "UP"}},
        {"level": {"value": 1.5, "relative": True, "edge": "RISING"}},
        {"level2": {"value": "x", "relative": False, "edge": "RISING"}},
    ],
)
def test_from_dict_rejects_invalid(change):
    data = MeasurementSpec(Kind.DELTA_T, "C1", Level(0.1), "C2", Level(0.2)).to_dict()
    data.update(change)
    with pytest.raises((ValueError, KeyError)):
        MeasurementSpec.from_dict(data)


def test_from_dict_rejects_missing_field():
    data = MeasurementSpec(Kind.AMPLITUDE, "C1").to_dict()
    del data["source"]
    with pytest.raises(KeyError):
        MeasurementSpec.from_dict(data)


# --- 1, 2: interpolated crossings (SC-003) -------------------------------------------------------


@pytest.mark.parametrize("falling", [False, True])
def test_ramp_crossing_interpolated(falling):
    dt, t0 = 1e-9, -50e-9
    k = np.arange(200)
    ramp = np.clip((k - 10) * 0.02, 0, 1)  # flat 0 V, linear edge over 50 samples, flat 1 V
    volts = 1 - ramp if falling else ramp
    level = 1 - 0.3037 if falling else 0.3037
    edge_ = Edge.FALLING if falling else Edge.RISING
    t = one(MeasurementSpec(Kind.TIME_AT_LEVEL, "C1", Level(level, edge=edge_)), wf(volts, dt, t0))
    assert abs(t - (t0 + 25.185 * dt)) < 0.01 * dt


def test_delta_t_between_shifted_edges():
    dt = 1e-10
    t = times(1000, dt)
    tau = 1.234e-9
    a = wf(edge(t, 50e-9, 1e-9), dt, name="C1")
    b = wf(edge(t, 50e-9 + tau, 1e-9), dt, name="C2")
    spec = MeasurementSpec(Kind.DELTA_T, "C1", Level(0.5), "C2", Level(0.5))
    assert abs(one(spec, a, b) - tau) < 0.01 * dt
    falling = MeasurementSpec(
        Kind.DELTA_T, "C1", Level(0.5, edge=Edge.FALLING), "C2", Level(0.5, edge=Edge.FALLING)
    )
    a2, b2 = wf(1 - a.volts, dt, name="C1"), wf(1 - b.volts, dt, name="C2")
    assert abs(one(falling, a2, b2) - tau) < 0.01 * dt


# --- 3: constant fraction ------------------------------------------------------------------------


def test_constant_fraction_independent_of_amplitude_and_polarity():
    dt = 5e-11
    t = times(4000, dt)
    shift = 1.717e-9
    big = wf(pulse(t, 30e-9, 0.10), dt, name="C2")
    small_negative = wf(-pulse(t, 30e-9 + shift, 0.03), dt, name="C3")
    spec = MeasurementSpec(Kind.DELTA_T, "C2", rel(0.2), "C3", rel(0.2))
    assert abs(one(spec, big, small_negative) - shift) < 0.02 * dt
    # Constant fraction: the crossing time does not move with the amplitude.
    at = MeasurementSpec(Kind.TIME_AT_LEVEL, "C2", rel(0.2))
    t_big = one(at, big)
    t_tiny = one(at, wf(pulse(t, 30e-9, 0.01), dt, name="C2"))
    assert abs(t_big - t_tiny) < 0.02 * dt


# --- 4: square wave ------------------------------------------------------------------------------


def square(t, period=100e-9, duty=0.3, high=2.5, rise=1e-9) -> np.ndarray:
    v = np.zeros_like(t)
    for start in np.arange(0, t[-1] + period, period):
        v += edge(t, start, rise) - edge(t, start + duty * period, rise)
    return high * v


def test_square_wave_frequency_duty_rise_time():
    dt = 5e-11
    t = times(20_000, dt)  # 1 µs, starting in the middle of a rising edge (cut first edge)
    clock = wf(square(t), dt)
    values = measure_all(
        [
            MeasurementSpec(Kind.FREQUENCY, "C1"),
            MeasurementSpec(Kind.PERIOD, "C1"),
            MeasurementSpec(Kind.DUTY_CYCLE, "C1"),
            MeasurementSpec(Kind.RISE_TIME, "C1"),
            MeasurementSpec(Kind.FALL_TIME, "C1"),
            MeasurementSpec(Kind.WIDTH, "C1"),
            MeasurementSpec(Kind.BASE, "C1"),
            MeasurementSpec(Kind.TOP, "C1"),
        ],
        {"C1": clock},
    )
    freq, period, duty, rise, fall, width, base, top = values
    assert freq == pytest.approx(10e6, rel=1e-3)
    assert period == pytest.approx(100e-9, rel=1e-3)
    assert duty == pytest.approx(30.0, abs=0.5)
    assert rise == pytest.approx(1e-9, rel=0.02)
    assert fall == pytest.approx(1e-9, rel=0.02)
    assert width == pytest.approx(30e-9, rel=1e-3)
    assert base == pytest.approx(0.0, abs=1e-3)
    assert top == pytest.approx(2.5, abs=1e-3)


# --- 5: pulses -----------------------------------------------------------------------------------


def test_pulse_on_noise_base_top_amplitude():
    rng = np.random.default_rng(5)
    dt = 5e-11
    t = times(10_000, dt)  # 500 ns, like the bench
    volts = 0.1 + pulse(t, 50e-9, 0.05) + rng.normal(0, 1e-3, t.size)
    w = wf(volts, dt, name="C2")
    base, top, amplitude = measure_all(
        [MeasurementSpec(k, "C2") for k in (Kind.BASE, Kind.TOP, Kind.AMPLITUDE)], {"C2": w}
    )
    assert base == pytest.approx(0.1, abs=5e-4)
    assert top == pytest.approx(float(w.volts.max()))
    assert amplitude == pytest.approx(top - base)

    negative = wf(-0.1 - pulse(t, 50e-9, 0.05) + rng.normal(0, 1e-3, t.size), dt, name="C2")
    base, top, amplitude = measure_all(
        [MeasurementSpec(k, "C2") for k in (Kind.BASE, Kind.TOP, Kind.AMPLITUDE)], {"C2": negative}
    )
    assert base == pytest.approx(-0.1, abs=5e-4)
    assert top == pytest.approx(float(negative.volts.min()))
    assert amplitude == pytest.approx(-0.05, abs=5e-3)


def test_area_of_rectangle():
    dt = 5e-11
    volts = np.zeros(2000)
    volts[500:700] = 0.2  # 200 samples = 10 ns
    area = one(MeasurementSpec(Kind.AREA, "C1"), wf(volts, dt))
    assert area == pytest.approx(0.2 * 10e-9, rel=1e-6)


def test_extremes_and_mean():
    volts = np.array([0.0, 1.0, -2.0, 3.0])
    values = measure_all(
        [MeasurementSpec(k, "C1") for k in (Kind.MAXIMUM, Kind.MINIMUM, Kind.PK_PK, Kind.MEAN)],
        {"C1": wf(volts)},
    )
    assert values == pytest.approx([3.0, -2.0, 5.0, 0.5])


# --- 6: no signal --------------------------------------------------------------------------------

RELATIVE_SPECS = [
    MeasurementSpec(Kind.TIME_AT_LEVEL, "C1", rel(0.5)),
    MeasurementSpec(Kind.EDGE_COUNT, "C1", rel(0.5)),
    MeasurementSpec(Kind.RISE_TIME, "C1"),
    MeasurementSpec(Kind.FALL_TIME, "C1"),
    MeasurementSpec(Kind.WIDTH, "C1"),
    MeasurementSpec(Kind.PERIOD, "C1"),
    MeasurementSpec(Kind.FREQUENCY, "C1"),
    MeasurementSpec(Kind.DUTY_CYCLE, "C1"),
]


def _relative_missed(w: Waveform) -> bool:
    values = measure_all(RELATIVE_SPECS, {"C1": w})
    time_at, edges, *rest = values
    return math.isnan(time_at) and edges == 0 and all(math.isnan(v) for v in rest)


def test_noise_only_misses_relative_quantities():
    rng = np.random.default_rng(6)
    w = wf(rng.normal(0, 1.2e-3, 10_000), 5e-11)
    assert _relative_missed(w)
    assert math.isfinite(one(MeasurementSpec(Kind.AMPLITUDE, "C1"), w))
    assert math.isfinite(one(MeasurementSpec(Kind.AREA, "C1"), w))


def test_flat_record_misses_relative_quantities():
    w = wf(np.full(1000, 0.3))
    assert _relative_missed(w)
    assert one(MeasurementSpec(Kind.AMPLITUDE, "C1"), w) == pytest.approx(0.0)


def test_one_code_wiggle_is_not_a_signal():
    step = 0.8e-3  # 20 mV/div at 25 codes/div
    volts = np.zeros(1000)
    volts[400:600] = step
    assert _relative_missed(wf(volts, step=step))
    # Without the digitiser step the noise estimate is 0 and the wiggle would be measured.
    assert not math.isnan(one(RELATIVE_SPECS[0], wf(volts, step=0.0)))


def test_reference_levels_of_long_record_use_a_subset_within_one_step():
    rng = np.random.default_rng(7)
    step = 0.8e-3
    n = 2_500_000
    volts = rng.normal(0.01, 1.2e-3, n)
    for at in rng.uniform(0, n, 40).astype(int):
        volts[at : at + 600] += 0.05 * np.exp(-np.arange(min(600, n - at)) / 150)
    volts = (np.round(volts / step) * step).astype(np.float32)
    base, top, noise, polarity = reference_levels(volts, step)
    lo, hi = float(volts.min()), float(volts.max())
    lower = volts[volts < (lo + hi) / 2]
    full_base = float(np.median(lower))
    full_noise = 1.4826 * float(np.median(np.abs(lower - full_base)))
    assert polarity == 1
    assert top == hi
    assert abs(base - full_base) <= step
    assert noise == pytest.approx(full_noise, rel=0.1)


# --- 7: hysteresis -------------------------------------------------------------------------------


def test_noise_on_a_slow_edge_counts_once():
    rng = np.random.default_rng(8)
    dt = 1e-10
    t = times(20_000, dt)
    slow = square(t, period=400e-9, duty=0.5, high=1.0, rise=8e-9)
    noisy = wf(slow + rng.normal(0, 5e-3, t.size), dt)
    count = one(MeasurementSpec(Kind.EDGE_COUNT, "C1", Level(0.5)), noisy)
    assert count == 4  # 400, 800, 1200, 1600 ns; the edge at 0 is cut by the record start
    assert count == one(MeasurementSpec(Kind.EDGE_COUNT, "C1", Level(0.5)), wf(slow, dt))


# --- 8: gate -------------------------------------------------------------------------------------


def _two_pulses():
    rng = np.random.default_rng(9)
    dt = 5e-11
    t = times(10_000, dt)  # 0..500 ns
    volts = pulse(t, 20e-9, 0.05) + pulse(t, 220e-9, 0.10) + rng.normal(0, 5e-4, t.size)
    return wf(volts, dt, name="C2")


def test_gate_limits_samples_but_base_from_whole_record():
    w = _two_pulses()
    gated = measure_all(
        [
            MeasurementSpec(Kind.AMPLITUDE, "C2"),
            MeasurementSpec(Kind.MAXIMUM, "C2"),
            MeasurementSpec(Kind.TIME_AT_LEVEL, "C2", rel(0.5)),
        ],
        {"C2": w},
        gate=(10e-9, 80e-9),
    )
    assert gated[0] == pytest.approx(0.05, rel=0.02)
    assert gated[1] == pytest.approx(0.05, rel=0.02)
    assert 20e-9 < gated[2] < 22e-9
    # A gate tightly around the first pulse's peak: still the whole record's base (~0 V).
    tight = one(MeasurementSpec(Kind.BASE, "C2"), w, gate=(21e-9, 25e-9))
    assert tight == pytest.approx(0.0, abs=1e-3)


@pytest.mark.parametrize("gate", [(50.01e-9, 50.02e-9), (600e-9, 700e-9), (-50e-9, -10e-9)])
def test_gate_with_fewer_than_two_samples_misses_everything(gate):
    w = _two_pulses()
    specs = [MeasurementSpec(k, "C2") for k in (Kind.MAXIMUM, Kind.AMPLITUDE, Kind.MEAN)]
    assert all(math.isnan(v) for v in measure_all(specs, {"C2": w}, gate))


# --- 9: missing channel --------------------------------------------------------------------------


def test_missing_channel_missed_others_unaffected():
    present = wf(np.array([0.0, 1.0, 2.0]), name="C1")
    values = measure_all(
        [
            MeasurementSpec(Kind.MAXIMUM, "C1"),
            MeasurementSpec(Kind.MAXIMUM, "C3"),
            MeasurementSpec(Kind.DELTA_T, "C1", Level(0.5), "C4", Level(0.5)),
        ],
        {"C1": present},
    )
    assert values[0] == 2.0
    assert math.isnan(values[1]) and math.isnan(values[2])


# --- 10: statistics ------------------------------------------------------------------------------


def test_statistics_ring_and_summary():
    stats = Statistics(capacity=5)
    for value in [1.0, 2.0, math.nan, 4.0, 5.0, 6.0, math.nan]:
        stats.add(value)
    assert stats.size == 5
    history = stats.history()
    np.testing.assert_array_equal(history, [math.nan, 4.0, 5.0, 6.0, math.nan])
    np.testing.assert_array_equal(stats.values(), [4.0, 5.0, 6.0])
    assert math.isnan(stats.last)
    s = stats.summary()
    assert (s.count, s.missed) == (3, 2)
    assert s.mean == pytest.approx(5.0)
    assert s.std == pytest.approx(np.std([4.0, 5.0, 6.0], ddof=1))
    assert (s.minimum, s.maximum) == (4.0, 6.0)


def test_statistics_empty_and_clear():
    stats = Statistics(capacity=3)
    s = stats.summary()
    assert (s.count, s.missed) == (0, 0)
    assert all(math.isnan(x) for x in (s.last, s.mean, s.std, s.minimum, s.maximum))
    stats.add(1.0)
    stats.clear()
    assert stats.size == 0 and stats.history().size == 0


# --- 11: Gaussian fit ----------------------------------------------------------------------------


def _histogram(values, bins=100, span=None):
    counts, edges = np.histogram(values, bins=bins, range=span)
    return (edges[:-1] + edges[1:]) / 2, counts


def test_gauss_fit_follows_the_main_peak_among_a_second_peak_and_tails():
    rng = np.random.default_rng(1)
    values = np.concatenate(
        [
            rng.normal(2.0, 0.12, 20_000),  # main peak
            rng.normal(2.9, 0.12, 6_000),  # smaller neighbour
            rng.normal(2.0, 0.6, 2_000),  # tails
        ]
    )
    centers, counts = _histogram(values, 120, (0.0, 4.0))
    fit = gauss_fit(centers, counts)
    assert fit is not None
    assert fit.mean == pytest.approx(2.0, rel=0.05)
    assert fit.sigma == pytest.approx(0.12, rel=0.05)
    assert fit.fwhm == pytest.approx(2.3548 * fit.sigma, rel=1e-3)
    assert fit(fit.mean) == pytest.approx(fit.amplitude)
    assert fit(fit.mean + fit.sigma) == pytest.approx(fit.amplitude * math.exp(-0.5))
    assert fit.amplitude == pytest.approx(counts.max(), rel=0.15)


def test_gauss_fit_of_a_plain_gaussian_in_a_narrow_range():
    values = np.random.default_rng(2).normal(-5e-9, 1e-10, 3000)
    centers, counts = _histogram(values, 40)  # min-max range: 3000 samples span about 7 sigma
    fit = gauss_fit(centers, counts)
    assert fit is not None
    assert fit.mean == pytest.approx(-5e-9, abs=0.05e-9 * 0.2)
    assert fit.sigma == pytest.approx(1e-10, rel=0.05)


def test_gauss_fit_needs_data_and_a_peak():
    centers = np.linspace(0, 1, 50)
    assert gauss_fit(centers, np.zeros(50)) is None
    few = np.zeros(50)
    few[20:23] = [1, 3, 2]  # 6 entries
    assert gauss_fit(centers, few) is None
    assert gauss_fit(centers, np.full(50, 40)) is None  # flat: no peak
    assert gauss_fit(centers[:2], np.array([50, 60])) is None
    spike = np.zeros(50)
    spike[25] = 500  # a single non-empty bin cannot be fitted
    assert gauss_fit(centers, spike) is None


# --- 12: histogram range -------------------------------------------------------------------------


def test_auto_range_ignores_far_outliers_and_keeps_the_main_peak():
    rng = np.random.default_rng(3)
    main = rng.normal(2e-9, 0.12e-9, 7500)
    outliers = rng.uniform(-100e-9, 100e-9, 2500)  # 25 %
    values = np.concatenate([main, outliers])
    low, high = histogram_range(values, RangeMode.AUTO_ROBUST)
    inside = ((main >= low) & (main <= high)).mean()
    assert inside >= 0.95
    assert high - low < 10e-9  # nowhere near the +-100 ns of the outliers
    assert low < 2e-9 < high


def test_auto_range_is_the_median_plus_minus_eight_robust_sigma():
    rng = np.random.default_rng(4)
    values = np.concatenate([rng.normal(10.0, 1.0, 5000), [1e6, -1e6]])
    low, high = histogram_range(values, RangeMode.AUTO_ROBUST)
    assert low == pytest.approx(10.0 - 8, abs=0.5)
    assert high == pytest.approx(10.0 + 8, abs=0.5)


def test_auto_range_never_exceeds_the_data():
    values = np.random.default_rng(5).normal(0.0, 1.0, 100)
    low, high = histogram_range(values, RangeMode.AUTO_ROBUST)
    assert (low, high) == (values.min(), values.max())  # +-8 sigma is wider than the data


def test_full_and_manual_ranges():
    values = np.array([3.0, 1.0, 2.0, np.nan, 100.0])
    assert histogram_range(values, RangeMode.FULL) == (1.0, 100.0)
    assert histogram_range(values, RangeMode.MANUAL, (-2.0, 5.0)) == (-2.0, 5.0)
    assert histogram_range(values, RangeMode.MANUAL, (5.0, -2.0)) == (-2.0, 5.0)  # any order


def test_constant_empty_and_degenerate_ranges_are_not_empty():
    for mode in RangeMode:
        for values in (np.full(10, 3.0), np.zeros(4), np.array([]), np.array([np.nan]), [7.0]):
            low, high = histogram_range(np.asarray(values), mode, (1.0, 1.0))
            assert high > low
    low, high = histogram_range(np.full(10, 3.0), RangeMode.AUTO_ROBUST)
    assert low < 3.0 < high


def test_auto_range_falls_back_to_min_max_when_the_mad_is_zero():
    values = np.concatenate([np.full(100, 1.0), [5.0, 9.0]])  # MAD = 0
    assert histogram_range(values, RangeMode.AUTO_ROBUST) == (1.0, 9.0)


def _crossings_per_sample(v, level, hysteresis):
    """Straightforward per-sample state machine (the original implementation)."""
    state = np.zeros(v.size, np.int8)
    state[v < level - hysteresis] = -1
    state[v >= level] = 1
    idx = np.flatnonzero(state)
    s = state[idx]
    return idx[1:][(s[1:] == 1) & (s[:-1] == -1)]


@pytest.mark.parametrize("seed", range(20))
def test_crossing_indices_match_the_per_sample_state_machine(seed):
    rng = np.random.default_rng(seed)
    v = np.cumsum(rng.normal(size=rng.integers(2, 3000))).astype(np.float32)
    v[rng.random(v.size) < 0.01] = np.nan  # NaN is neither armed nor fired
    level, hysteresis = float(rng.normal() * 5), float(rng.choice([0.0, 0.5, 3.0]))
    expected = _crossings_per_sample(v, level, hysteresis)
    np.testing.assert_array_equal(crossing_indices(v, level, hysteresis), expected)
    falling = _crossings_per_sample(-v, -level, hysteresis)
    np.testing.assert_array_equal(crossing_indices(v, level, hysteresis, rising=False), falling)


@pytest.mark.parametrize("seed", range(10))
def test_gauss_fit_of_a_sparse_histogram_is_not_a_single_bin(seed):
    """~160 entries in 100 bins (a minute on the bench): the highest bin is mostly noise."""
    values = np.random.default_rng(seed).normal(8e-9, 74e-12, 160)
    centers, counts = _histogram(values, 100, (7.5e-9, 8.5e-9))
    fit = gauss_fit(centers, counts)
    assert fit is not None
    assert fit.mean == pytest.approx(8e-9, abs=20e-12)
    assert fit.sigma == pytest.approx(74e-12, rel=0.3)
