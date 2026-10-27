"""Accuracy of the synthetic bench: the scene is right, then the analysis recovers its truth.

No GUI: ``SyntheticAcquisition`` is generated directly with fixed seeds.
"""

import time
from dataclasses import dataclass

import numpy as np
import pytest
from synthetic_scope import (
    CODES_PER_DIV,
    ChannelSetup,
    Scene,
    SyntheticAcquisition,
    SyntheticScope,
    acquisition_block,
    fit_vertical_scale,
    quantize,
)

from scope_gui.analysis import (
    Edge,
    Kind,
    Level,
    MeasurementSpec,
    RangeMode,
    gauss_fit,
    histogram_range,
    measure_all,
)
from scope_gui.models import Waveform
from scope_gui.wavedesc import decode_waveform

N_ACQUISITIONS = 2000
FAST_POINTS = 2000  # 250 ps/sample instead of 50 ps: 2,000 acquisitions in a few seconds


# --- helpers shared with the analysis checks (T013, T021) ---------------------------------------
def make_scene(**changes) -> Scene:
    """A default scene with some fields replaced (``channels`` may be passed whole)."""
    return Scene(**changes)


def generate(scene: Scene, n: int, seed: int):
    """``n`` acquisitions of ``scene`` from one seeded random generator."""
    rng = np.random.default_rng(seed)
    for _ in range(n):
        yield SyntheticAcquisition(scene, rng)


def waveforms_of(acq: SyntheticAcquisition, trigger_time: float = 0.0) -> dict[str, Waveform]:
    """The enabled channels of ``acq`` as the driver delivers them: through the scope's 8-bit
    codes (clipped to -128...127) and the descriptor gain/offset, in float32, with ``step`` set
    to the volts per code. Same arithmetic as ``wavedesc.decode_waveform``."""
    sc = acq.scene
    out = {}
    for name, setup in sc.channels.items():
        if not setup.enabled:
            continue
        codes, gain = quantize(acq.volts[name], setup)
        volts = codes.astype(np.float32) * np.float32(gain) - np.float32(setup.offset)
        out[name] = Waveform(
            channel=name,
            volts=volts,
            t0=sc.t0,
            dt=float(np.float32(sc.dt)),
            trigger_time=trigger_time,
            received_at=time.monotonic(),
            step=float(np.float32(gain)),
        )
    return out


@dataclass
class Population:
    """True values (and a few waveform summaries) of many acquisitions of one scene."""

    npe_a: np.ndarray
    npe_b: np.ndarray
    arrival_a: np.ndarray
    arrival_b: np.ndarray
    fired: np.ndarray
    c4_peak: np.ndarray  # max |C4| of each acquisition
    c4_min: np.ndarray


def collect(scene: Scene, n: int, seed: int) -> Population:
    rows = [
        (
            a.npe_a,
            a.npe_b,
            a.arrival_a,
            a.arrival_b,
            a.fired,
            np.abs(a.volts["C4"]).max(),
            a.volts["C4"].min(),
        )
        for a in generate(scene, n, seed)
    ]
    return Population(*(np.array(column) for column in zip(*rows, strict=True)))


@pytest.fixture(scope="module")
def population() -> Population:
    return collect(make_scene(points=FAST_POINTS), N_ACQUISITIONS, seed=12345)


# --- scene --------------------------------------------------------------------------------------
def test_default_scene_values():
    sc = Scene()
    assert sc.clock_period == pytest.approx(100e-9)  # 10 MHz
    assert (sc.clock_high, sc.clock_jitter) == (2.5, pytest.approx(15e-12))
    assert sc.mean_pe == 3.0
    assert sc.pe_volts == pytest.approx(0.020)
    assert sc.gain_spread == pytest.approx(0.10)
    assert (sc.rise, sc.decay) == (pytest.approx(1e-9), pytest.approx(30e-9))
    assert (sc.arrival_a, sc.arrival_b) == (pytest.approx(35e-9), pytest.approx(37e-9))
    assert (sc.jitter_a, sc.jitter_b) == (pytest.approx(70e-12), pytest.approx(90e-12))
    assert sc.dark_rate == pytest.approx(1e6)
    assert sc.sipm_noise == pytest.approx(1.2e-3)
    assert sc.bandwidth == pytest.approx(1e9)
    assert sc.nim_level == pytest.approx(-0.8)
    assert sc.nim_width == pytest.approx(20e-9)
    assert sc.nim_delay == pytest.approx(8e-9)
    assert sc.discriminator == pytest.approx(0.030)
    assert sc.time_per_div == pytest.approx(50e-9)
    assert sc.points == 10_000
    assert sc.dt == pytest.approx(50e-12)
    assert sc.t0 == pytest.approx(-100e-9)  # trigger (t = 0) two divisions from the left


def test_default_channel_setups():
    ch = Scene().channels
    expected = {
        "C1": (1.0, -0.25),
        "C2": (0.020, -0.060),
        "C3": (0.020, 0.060),
        "C4": (0.5, 1.0),
    }
    assert {name: (c.volts_per_div, c.offset) for name, c in ch.items()} == {
        name: (pytest.approx(v), pytest.approx(o)) for name, (v, o) in expected.items()
    }
    assert all(c.enabled for c in ch.values())
    assert all(isinstance(c, ChannelSetup) for c in ch.values())


def test_scenes_do_not_share_channel_setups():
    a, b = Scene(), Scene()
    a.channels["C2"].volts_per_div = 0.002
    assert b.channels["C2"].volts_per_div == pytest.approx(0.020)


def test_mean_photoelectrons_is_three(population):
    assert population.npe_a.mean() == pytest.approx(3.0, abs=0.15)
    assert population.npe_b.mean() == pytest.approx(3.0, abs=0.15)


def test_share_of_empty_acquisitions_is_exp_minus_three(population):
    empty = (population.npe_a == 0).mean()
    assert empty == pytest.approx(np.exp(-3), abs=0.015)  # about 5 %


def test_discriminator_fires_only_with_a_signal(population):
    empty = population.npe_a == 0
    assert empty.sum() > 30
    assert not population.fired[empty].any()
    assert population.c4_peak[empty].max() < 0.1  # noise only: 10 mV rms, C4 stays near 0 V
    assert population.fired[population.npe_a >= 2].all()  # 2 pe = 40 mV > 30 mV
    assert population.c4_min[population.fired].max() < -0.6  # the -0.8 V NIM pulse is there


def test_true_arrival_difference_has_the_combined_jitter(population):
    sigma = np.std(population.arrival_b - population.arrival_a, ddof=1)
    assert sigma == pytest.approx(np.hypot(70e-12, 90e-12), rel=0.10)  # about 114 ps
    assert (population.arrival_b - population.arrival_a).mean() == pytest.approx(2e-9, abs=20e-12)


def test_same_seed_gives_identical_volts():
    scene = make_scene(points=FAST_POINTS)
    first = next(generate(scene, 1, seed=7))
    again = next(generate(scene, 1, seed=7))
    other = next(generate(scene, 1, seed=8))
    for ch in ("C1", "C2", "C3", "C4"):
        assert np.array_equal(first.volts[ch], again.volts[ch])
    assert not np.array_equal(first.volts["C2"], other.volts["C2"])
    assert (first.npe_a, first.arrival_a) == (again.npe_a, again.arrival_a)


def test_scope_with_a_seed_is_reproducible():
    one = SyntheticScope(seed=3, rate_hz=1000, on_demand=True)
    two = SyntheticScope(seed=3, rate_hz=1000, on_demand=True)
    for scope in (one, two):
        scope.write("C1:WF? DESC")
    assert np.array_equal(one.current.volts["C3"], two.current.volts["C3"])


def test_noise_is_band_limited_with_the_scene_rms():
    scene = make_scene(mean_pe=0.0, dark_rate=0.0)  # C2/C3 hold only noise
    acq = next(generate(scene, 1, seed=1))
    for ch in ("C2", "C3"):
        v = acq.volts[ch]
        assert v.std() == pytest.approx(1.2e-3, rel=0.10)
        # 0.35 / 1 GHz is 7 samples at 20 GS/s: neighbouring samples are strongly correlated
        assert np.corrcoef(v[:-1], v[1:])[0, 1] > 0.8


def test_polarities_and_pulse_height():
    scene = make_scene(mean_pe=20.0, dark_rate=0.0, points=FAST_POINTS)
    acq = next(generate(scene, 1, seed=5))
    assert acq.volts["C2"].max() == pytest.approx(0.020 * acq.npe_a, rel=0.2)
    assert acq.volts["C2"].min() > -0.02
    assert acq.volts["C3"].min() == pytest.approx(-0.020 * acq.npe_b, rel=0.2)
    assert acq.volts["C3"].max() < 0.02
    assert acq.volts["C1"].max() == pytest.approx(2.5, abs=0.15)
    assert acq.volts["C1"].min() == pytest.approx(0.0, abs=0.15)


def test_clock_trigger_edge_at_time_zero():
    acq = next(generate(make_scene(), 1, seed=2))
    c1 = acq.volts["C1"]
    crossings = acq.times[np.flatnonzero((c1[:-1] < 1.25) & (c1[1:] >= 1.25))]
    at_zero = crossings[np.abs(crossings) < 50e-9]
    next_edge = crossings[np.abs(crossings - 100e-9) < 50e-9]  # 10 MHz: one period later
    assert at_zero == pytest.approx([0.0], abs=0.2e-9)
    assert next_edge == pytest.approx([100e-9], abs=0.2e-9)


# --- 8-bit codes --------------------------------------------------------------------------------
def test_waveforms_of_matches_the_decoded_block():
    scope = SyntheticScope(seed=4, rate_hz=1000, on_demand=True)
    scope.write("C1:WF? DESC")
    acq = scope.current
    waves = waveforms_of(acq)
    assert set(waves) == {"C1", "C2", "C3", "C4"}
    for name, wave in waves.items():
        desc, volts = decode_waveform(acquisition_block(acq, name, "ALL"))
        assert np.array_equal(wave.volts, volts)
        assert wave.step == pytest.approx(desc.vertical_gain)
        assert wave.t0 == pytest.approx(desc.horiz_offset)
        assert wave.dt == pytest.approx(desc.horiz_interval)


def test_waveforms_of_quantises_to_codes_and_skips_disabled_channels():
    scene = make_scene(points=FAST_POINTS)
    scene.channels["C4"].enabled = False
    acq = next(generate(scene, 1, seed=6))
    waves = waveforms_of(acq)
    assert "C4" not in waves
    c2 = waves["C2"]
    codes = (c2.volts + np.float32(scene.channels["C2"].offset)) / np.float32(c2.step)
    assert np.allclose(codes, np.round(codes), atol=0.01)  # whole codes only
    assert c2.step == pytest.approx(scene.channels["C2"].volts_per_div / CODES_PER_DIV)


def test_waveforms_of_clips_at_the_screen_edge():
    scene = make_scene(mean_pe=30.0, points=FAST_POINTS)
    scene.channels["C2"] = ChannelSetup(0.002, 0.0)  # 2 mV/div: a 600 mV pulse is off screen
    acq = next(generate(scene, 1, seed=9))
    c2 = waveforms_of(acq)["C2"]
    edge = 127 * 0.002 / CODES_PER_DIV  # +5.08 div
    assert acq.volts["C2"].max() > 10 * edge
    assert c2.volts.max() == pytest.approx(edge, rel=1e-4)
    assert c2.volts.min() >= -128 * 0.002 / CODES_PER_DIV - 1e-6


# --- analysis on the synthetic scene (T013, T021) ------------------------------------------
CF_DELTA_T = MeasurementSpec(
    Kind.DELTA_T, "C2", Level(0.2, True, Edge.RISING), "C3", Level(0.2, True, Edge.RISING)
)


def measure_population(scene: Scene, specs: list[MeasurementSpec], n: int, seed: int):
    """``measure_all`` over ``n`` acquisitions: (values[spec, n], true arrival_b - arrival_a)."""
    values = np.empty((len(specs), n))
    truth = np.empty(n)
    for i, acq in enumerate(generate(scene, n, seed)):
        values[:, i] = measure_all(specs, waveforms_of(acq))
        truth[i] = acq.arrival_b - acq.arrival_a
    return values, truth


@pytest.fixture(scope="module")
def bright_dt():
    """Δt of constant-fraction crossings with 20 photoelectrons per pulse (T013, T021)."""
    # At the default 20 mV/div, 20 photoelectrons clip at ~160 mV and dark-count pile-ups then
    # cross the 20 % level (a real effect): give C2/C3 a scale that holds the whole pulse.
    scene = fit_vertical_scale(make_scene(mean_pe=20.0))
    values, truth = measure_population(scene, [CF_DELTA_T], N_ACQUISITIONS, 21)
    return values[0], truth


def test_constant_fraction_delta_t_mean_and_sigma(bright_dt):
    measured, truth = bright_dt
    assert np.isfinite(measured).all()
    assert measured.mean() == pytest.approx(2e-9, abs=20e-12)
    true_sigma = np.std(truth, ddof=1)  # the combined jitter of these very acquisitions
    assert true_sigma == pytest.approx(np.hypot(70e-12, 90e-12), rel=0.10)
    assert np.std(measured, ddof=1) == pytest.approx(true_sigma, rel=0.10)


def test_clock_frequency_is_ten_megahertz():
    spec = MeasurementSpec(Kind.FREQUENCY, "C1")
    values, _ = measure_population(make_scene(), [spec], 100, seed=22)
    assert np.isfinite(values).all()
    assert values[0] == pytest.approx(10e6, rel=1e-3)


# --- distributions (T021) ------------------------------------------------------------------
AMPLITUDE_C2 = MeasurementSpec(Kind.AMPLITUDE, "C2")
COMBINED_JITTER = float(np.hypot(70e-12, 90e-12))


def histogram_fit(values: np.ndarray, bins: int = 100):
    """What the histogram panel does: robust range, histogram of the finite values, Gaussian fit."""
    values = values[np.isfinite(values)]
    low, high = histogram_range(values, RangeMode.AUTO_ROBUST)
    counts, edges = np.histogram(values, bins, (low, high))
    return gauss_fit((edges[:-1] + edges[1:]) / 2, counts)


def histogram_peaks(values: np.ndarray, bin_width: float, top: float, floor: float) -> list[float]:
    """Positions of the peaks of a spectrum: local maxima of the smoothed histogram above
    ``floor`` volts and a quarter of the highest, each refined as the centroid of its bins."""
    counts, edges = np.histogram(values, np.arange(0, top + bin_width / 2, bin_width))
    x = (edges[:-1] + edges[1:]) / 2
    smooth = np.convolve(counts, np.array([1, 2, 3, 4, 3, 2, 1.0]) / 16, mode="same")
    peaks = []
    for i in range(5, len(smooth) - 5):
        if smooth[i] == smooth[i - 5 : i + 6].max() and smooth[i] > 0.25 * smooth.max():
            if x[i] > floor:
                near = np.abs(x - x[i]) <= 5 * bin_width
                peaks.append(float((x[near] * counts[near]).sum() / counts[near].sum()))
    return peaks


@pytest.fixture(scope="module")
def default_population():
    """Δt and amplitude C2 of the default scene (100 ps samples keep it quick)."""
    scene = make_scene(points=5000)
    values, truth = measure_population(scene, [CF_DELTA_T, AMPLITUDE_C2], N_ACQUISITIONS, 31)
    return values, truth


def test_fit_of_the_constant_fraction_histogram_with_bright_pulses(bright_dt):
    measured, truth = bright_dt
    fit = histogram_fit(measured)
    assert fit is not None
    assert fit.mean == pytest.approx(2e-9, abs=20e-12)
    assert fit.sigma == pytest.approx(np.std(truth, ddof=1), rel=0.10)


def test_fit_of_the_constant_fraction_histogram_in_the_default_scene(default_population):
    values, truth = default_population
    delta_t = values[0]
    assert np.isfinite(delta_t).mean() > 0.9  # most acquisitions have a pulse on both channels
    fit = histogram_fit(delta_t)
    assert fit is not None
    assert fit.mean == pytest.approx(2e-9, abs=20e-12)
    assert fit.sigma == pytest.approx(COMBINED_JITTER, rel=0.15)


def test_amplitude_histogram_shows_the_photoelectron_peaks(default_population):
    amplitude = default_population[0][1]
    peaks = histogram_peaks(amplitude, 1e-3, 0.2, floor=0.010)  # above the noise-only peak
    assert len(peaks) >= 4
    spacing = (peaks[3] - peaks[0]) / 3  # first four photoelectron peaks
    assert spacing == pytest.approx(20e-3, rel=0.05)


def test_amplitude_histogram_of_a_clipped_channel_peaks_at_the_clipping_level():
    scene = make_scene(points=FAST_POINTS)
    scene.channels["C2"] = ChannelSetup(0.005, -0.015)  # 5 mV/div, baseline 3 div below centre
    values, _ = measure_population(scene, [AMPLITUDE_C2], 400, seed=32)
    amplitude = values[0]
    gain = 0.005 / CODES_PER_DIV
    clip = 127 * gain + 0.015  # highest decoded voltage; the baseline is at 0 V
    counts, edges = np.histogram(amplitude, 100, (0, 0.06))
    highest = (edges[np.argmax(counts)] + edges[np.argmax(counts) + 1]) / 2
    assert highest == pytest.approx(clip, abs=1.5e-3)
    assert amplitude.max() <= clip + 3 * gain  # nothing above the screen edge
    assert (amplitude > clip - 2e-3).mean() > 0.4  # most pulses (2+ pe) are clipped


def binned_medians(x: np.ndarray, y: np.ndarray, edges) -> np.ndarray:
    ok = np.isfinite(x) & np.isfinite(y)
    pairs = zip(edges[:-1], edges[1:], strict=True)
    return np.array([np.median(y[ok & (x >= a) & (x < b)]) for a, b in pairs])


AMPLITUDE_BINS = (0.03, 0.05, 0.07, 0.09, 0.12, 0.2)  # volts: ~2 to 10 photoelectrons


def test_time_walk_of_a_fixed_threshold(default_population):
    """Quickstart B5: with a fixed volt level, larger pulses cross it earlier (time walk), as
    the correlation view shows; the constant-fraction Δt does not walk."""
    fixed = MeasurementSpec(Kind.DELTA_T, "C1", Level(1.25), "C2", Level(0.03))
    (dt, amplitude), _ = measure_population(make_scene(points=5000), [fixed, AMPLITUDE_C2], 400, 41)
    walk = binned_medians(amplitude, dt, AMPLITUDE_BINS)
    assert (np.diff(walk) < 0).all()  # earlier for every larger amplitude bin
    assert walk[0] - walk[-1] > 0.5e-9
    (cf, cf_amplitude), _ = default_population
    flat = binned_medians(cf_amplitude, cf, AMPLITUDE_BINS)
    assert np.ptp(flat) < (walk[0] - walk[-1]) / 5
