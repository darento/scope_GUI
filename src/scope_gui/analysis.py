"""Measurements on the waveforms already received for display (no instrument I/O).

Everything here is pure numpy: it works on the samples the GUI got from the worker, so measuring
never sends anything to the scope (FR-020). Definitions: specs/002-waveform-analysis/data-model.md.

Reference levels (research R2): per channel and acquisition the record is split at its mid-level.
Square-like signals use the medians of the samples below/above it as base and top; narrow pulses
(fewer than ``PULSE_FRACTION`` of the samples on one side, e.g. SiPM signals) use the baseline as
base and the peak inside the gate as top, so for negative pulses top is below base. Base and noise
always come from the whole record. Percent levels, rise/fall time, width, period and duty cycle
are relative to these: 0 % = base, 100 % = top, and the *leading* edge goes from base to top
whatever the polarity.
"""

import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from functools import cached_property

import numpy as np

from .models import CHANNELS, Waveform

PULSE_FRACTION = 0.2  # fewer samples than this beyond the mid-level -> narrow pulses, top = peak
HYSTERESIS = 0.05  # fraction of |top - base| a level must be re-armed by before it fires again
NOISE_HYSTERESIS = 3.0  # ... and at least this many times the noise rms
MIN_SNR = 5.0  # |top - base| below this many noise rms: no pulse, relative quantities missed
HISTORY = 100_000  # values kept per measurement
REFERENCE_SAMPLES = 100_000  # reference medians use at most this many evenly spaced samples (R1)
FWHM_PER_SIGMA = 2 * math.sqrt(2 * math.log(2))


class Edge(Enum):
    RISING = "Rising"
    FALLING = "Falling"


class Kind(Enum):
    DELTA_T = "Δt @ level"
    TIME_AT_LEVEL = "Time @ level"
    EDGE_COUNT = "Edge count @ level"
    AMPLITUDE = "Amplitude"
    BASE = "Base"
    TOP = "Top"
    MAXIMUM = "Maximum"
    MINIMUM = "Minimum"
    PK_PK = "Pk-Pk"
    MEAN = "Mean"
    AREA = "Area"
    RISE_TIME = "Rise time 10-90%"
    FALL_TIME = "Fall time 90-10%"
    WIDTH = "Width @ 50%"
    PERIOD = "Period"
    FREQUENCY = "Frequency"
    DUTY_CYCLE = "Duty cycle"

    @property
    def unit(self) -> str:
        if self in _TIME_KINDS:
            return "s"
        return {
            Kind.FREQUENCY: "Hz",
            Kind.DUTY_CYCLE: "%",
            Kind.EDGE_COUNT: "",
            Kind.AREA: "V·s",
        }.get(self, "V")

    @property
    def levels(self) -> int:
        """Number of user-set levels the measurement needs (0, 1 or 2)."""
        return {Kind.DELTA_T: 2, Kind.TIME_AT_LEVEL: 1, Kind.EDGE_COUNT: 1}.get(self, 0)


_TIME_KINDS = {
    Kind.DELTA_T,
    Kind.TIME_AT_LEVEL,
    Kind.RISE_TIME,
    Kind.FALL_TIME,
    Kind.WIDTH,
    Kind.PERIOD,
}


@dataclass(frozen=True)
class Level:
    """A threshold: volts, or a fraction (0-1) of base->top when ``relative`` (constant fraction).

    For relative levels RISING means the leading edge (base -> top) whatever the polarity.
    """

    value: float = 0.0
    relative: bool = False
    edge: Edge = Edge.RISING

    def __post_init__(self):
        if not isinstance(self.edge, Edge):
            raise ValueError(f"invalid edge {self.edge!r}")
        if not math.isfinite(self.value) or (self.relative and not 0 <= self.value <= 1):
            raise ValueError(f"invalid level {self.value!r}")

    def label(self) -> str:
        if self.relative:
            lead = "lead" if self.edge is Edge.RISING else "trail"
            return f"{lead} {self.value * 100:g}%"
        arrow = "↑" if self.edge is Edge.RISING else "↓"
        return f"{arrow} {si_format(self.value, 'V')}"


@dataclass(frozen=True)
class MeasurementSpec:
    kind: Kind
    source: str
    level: Level = field(default_factory=Level)
    source2: str = "C2"
    level2: Level = field(default_factory=Level)

    def __post_init__(self):
        if not isinstance(self.kind, Kind):
            raise ValueError(f"invalid measurement type {self.kind!r}")
        for source in (self.source, self.source2):
            if source not in CHANNELS:
                raise ValueError(f"invalid channel {source!r}")
        if not (isinstance(self.level, Level) and isinstance(self.level2, Level)):
            raise ValueError("invalid level")

    @property
    def channels(self) -> frozenset[str]:
        """Channels the measurement reads; more than one = cross-channel (003 FR-015)."""
        if self.kind is Kind.DELTA_T:
            return frozenset((self.source, self.source2))
        return frozenset((self.source,))

    @property
    def name(self) -> str:
        if self.kind is Kind.DELTA_T:
            return f"Δt {self.source} {self.level.label()} → {self.source2} {self.level2.label()}"
        if self.kind.levels:
            return f"{self.kind.value.removesuffix(' @ level')} {self.source} {self.level.label()}"
        return f"{self.kind.value} {self.source}"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["kind"] = self.kind.name
        for key in ("level", "level2"):
            data[key]["edge"] = data[key]["edge"].name
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "MeasurementSpec":
        """Inverse of ``to_dict``; ValueError/KeyError (or TypeError) for invalid data."""

        def level(d: dict) -> Level:
            return Level(float(d["value"]), bool(d["relative"]), Edge[d["edge"]])

        return cls(
            Kind[data["kind"]],
            data["source"],
            level(data["level"]),
            data["source2"],
            level(data["level2"]),
        )


def si_format(value: float, unit: str) -> str:
    """Engineering format with 4 significant digits: 0.03 V -> "30 mV"; NaN -> "—"."""
    if not math.isfinite(value):
        return "—"
    if value == 0:
        return f"0 {unit}"
    prefixes = {-4: "p", -3: "n", -2: "µ", -1: "m", 0: "", 1: "k", 2: "M", 3: "G"}
    power = max(-4, min(3, math.floor(math.log10(abs(value)) / 3)))
    scaled = float(f"{value / 1000**power:.4g}")
    if abs(scaled) >= 1000 and power < 3:  # 0.99999 V rounds to 1000 mV: show 1 V
        power += 1
        scaled = float(f"{scaled / 1000:.4g}")
    return f"{scaled:g} {prefixes[power]}{unit}"


# --- crossings -------------------------------------------------------------------------------


def crossing_indices(
    v: np.ndarray, level: float, hysteresis: float = 0.0, rising: bool = True
) -> np.ndarray:
    """Indices ``j`` where ``v`` crosses ``level`` (upwards, or downwards if not ``rising``)
    between ``j - 1`` and ``j``.

    A crossing counts only after the signal was beyond ``level -/+ hysteresis`` (re-armed), so
    noise riding on the level does not fire it again. Works on the few transitions of the two
    thresholds, not on every sample: 2.5M points cost a handful of boolean passes (research R1).
    """
    if rising:
        fired, armed = v >= level, v < level - hysteresis
    else:
        fired, armed = v <= level, v > level + hysteresis
    fires = np.flatnonzero(fired[1:] & ~fired[:-1]) + 1
    if not fires.size:
        return fires
    leaves = np.flatnonzero(~fired[1:] & fired[:-1]) + 1  # where the level was left again
    arms = np.flatnonzero(armed[1:] & ~armed[:-1]) + 1
    if armed[0]:
        arms = np.concatenate(([0], arms))
    # Since the level was last left (or the record start), was the signal re-armed?
    k = np.searchsorted(leaves, fires, side="right") - 1
    since = np.zeros_like(fires)
    since[k >= 0] = leaves[k[k >= 0]]
    rearmed = np.searchsorted(arms, fires) > np.searchsorted(arms, since)
    return fires[rearmed]


def _rms(v: np.ndarray, centre: float) -> float:
    """Robust noise rms: 1.4826 x median absolute deviation (equals the rms for Gaussian noise)."""
    return 1.4826 * float(np.median(np.abs(v - centre)))


def _baseline(v: np.ndarray) -> tuple[float, float]:
    """(level, noise rms) of a flat level that pulse tails or edges may lean on.

    The median alone is pulled towards the tails of pulses sitting among the samples (~2 mV for
    a SiPM record); the most populated value (histogram mode) is not. The level is the median of
    the samples within one noise rms of that mode, which is unbiased for symmetric noise.
    """
    level = float(np.median(v))
    noise = _rms(v, level)
    if noise > 0:
        counts, edges = np.histogram(v, bins=40, range=(level - 5 * noise, level + 5 * noise))
        peak = int(np.argmax(counts))
        mode = float(edges[peak] + edges[peak + 1]) / 2
        near = v[np.abs(v - mode) <= noise]
        if near.size:
            level = float(np.median(near))
            noise = _rms(v, level)
    return level, noise


def reference_levels(volts: np.ndarray, step: float = 0.0) -> tuple[float, float, float, int]:
    """(base, top, noise rms, polarity) of a whole record; polarity 0 = square-like.

    The medians use at most ``REFERENCE_SAMPLES`` evenly spaced samples (research R1): the base
    of a 2.5M-point record costs 2 ms instead of 41 ms and moves by less than a digitiser step.
    The extremes use every sample, so a narrow pulse is never missed. The noise is a median
    absolute deviation, so the tail of a pulse among the base samples does not inflate it, and
    it is at least one digitiser ``step``: a flat record or a one-code wiggle is not a signal.
    """
    lo, hi = float(volts.min()), float(volts.max())
    v = volts[:: -(-volts.size // REFERENCE_SAMPLES)]
    upper = v >= (lo + hi) / 2
    fraction = float(upper.mean())
    if fraction < PULSE_FRACTION:  # mostly low: positive pulses
        (base, noise), top, polarity = _baseline(v[~upper]), hi, 1
    elif fraction > 1 - PULSE_FRACTION:  # mostly high: negative pulses (or flat)
        (base, noise), top, polarity = _baseline(v[upper]), lo, -1
    else:
        (base, noise), (top, _), polarity = _baseline(v[~upper]), _baseline(v[upper]), 0
    return base, top, max(noise, step), polarity


class Trace:
    """One channel's samples inside the gate, with lazily computed reference levels.

    Base and noise always come from the whole record: a gate drawn tightly around a pulse would
    otherwise be mostly pulse and give a wrong base. The gate only limits where crossings and
    the peak are searched and which samples are measured.
    """

    def __init__(self, waveform: Waveform, gate: tuple[float, float] | None = None):
        n = waveform.volts.size
        i0, i1 = 0, n
        if gate is not None and waveform.dt > 0:
            start, end = sorted(gate)
            i0 = max(0, math.ceil((start - waveform.t0) / waveform.dt))
            i1 = min(n, math.floor((end - waveform.t0) / waveform.dt) + 1)
        self.record = waveform.volts
        self.step = waveform.step
        self.v = waveform.volts[i0 : max(i0, i1)]
        self.t0 = waveform.t0 + i0 * waveform.dt
        self.dt = waveform.dt
        self._crossings: dict[tuple[float, bool, float], np.ndarray] = {}

    @property
    def empty(self) -> bool:
        return self.v.size < 2

    @cached_property
    def _reference(self) -> tuple[float, float, float, int]:
        return reference_levels(self.record, self.step)

    @cached_property
    def _levels(self) -> tuple[float, float, float]:
        """(base, top, noise rms); for pulses top is the peak inside the gate."""
        base, top, noise, polarity = self._reference
        if polarity > 0:
            top = float(self.v.max())
        elif polarity < 0:
            top = float(self.v.min())
        return base, top, noise

    @property
    def base_top(self) -> tuple[float, float]:
        return self._levels[:2]

    @property
    def amplitude(self) -> float:
        base, top = self.base_top
        return top - base

    @property
    def has_pulse(self) -> bool:
        """The signal stands out of its noise, so percentages of its amplitude mean something."""
        base, top, noise = self._levels
        return abs(top - base) > MIN_SNR * noise

    def crossings(self, level: Level) -> np.ndarray:
        """Interpolated times of every crossing of ``level`` (s, relative to the trigger)."""
        base, top, noise = self._levels
        hysteresis = max(HYSTERESIS * abs(top - base), NOISE_HYSTERESIS * noise)
        if level.relative:
            if not self.has_pulse:
                return np.empty(0)
            volts = base + level.value * (top - base)
            rising = (level.edge is Edge.RISING) == (top >= base)
        else:
            volts, rising = level.value, level.edge is Edge.RISING
        key = (volts, rising, hysteresis)  # several measurements often share a crossing
        if key not in self._crossings:
            v = self.v
            j = crossing_indices(v, volts, hysteresis, rising)
            before, after = v[j - 1].astype(np.float64), v[j].astype(np.float64)
            fraction = (volts - before) / (after - before)
            self._crossings[key] = self.t0 + (j - 1 + fraction) * self.dt
        return self._crossings[key]

    def first_crossing(self, level: Level) -> float:
        times = self.crossings(level)
        return float(times[0]) if times.size else math.nan

    def leading(self, fraction: float) -> np.ndarray:
        return self.crossings(Level(fraction, True, Edge.RISING))

    def trailing(self, fraction: float) -> np.ndarray:
        return self.crossings(Level(fraction, True, Edge.FALLING))


def _first_after(times: np.ndarray, t: float) -> float:
    later = times[times > t]
    return float(later[0]) if later.size else math.nan


def _rise_time(tr: Trace) -> float:
    """First complete leading edge: the 90 % crossing and the last 10 % crossing before it."""
    t90, t10 = tr.leading(0.9), tr.leading(0.1)
    before = np.searchsorted(t10, t90) - 1
    ok = np.flatnonzero(before >= 0)
    if not ok.size:
        return math.nan
    k = ok[0]
    return float(t90[k] - t10[before[k]])


def _fall_time(tr: Trace) -> float:
    t90 = tr.trailing(0.9)
    if not t90.size:
        return math.nan
    return _first_after(tr.trailing(0.1), t90[0]) - float(t90[0])


def _width(tr: Trace) -> float:
    lead = tr.leading(0.5)
    if not lead.size:
        return math.nan
    return _first_after(tr.trailing(0.5), lead[0]) - float(lead[0])


def _period(tr: Trace) -> float:
    lead = tr.leading(0.5)
    if lead.size < 2:
        return math.nan
    return float(lead[-1] - lead[0]) / (lead.size - 1)


def _duty_cycle(tr: Trace) -> float:
    lead, trail = tr.leading(0.5), tr.trailing(0.5)
    if lead.size < 2 or not trail.size:
        return math.nan
    nxt = np.searchsorted(trail, lead[:-1])
    ok = nxt < trail.size
    ends = trail[np.minimum(nxt, trail.size - 1)]
    ok &= ends < lead[1:]
    if not ok.any():
        return math.nan
    widths = ends[ok] - lead[:-1][ok]
    return 100 * float(widths.mean()) / _period(tr)


def measure(spec: MeasurementSpec, traces: dict[str, Trace]) -> float:
    """Value of one measurement for one acquisition, or NaN when it cannot be made."""
    tr = traces.get(spec.source)
    if tr is None or tr.empty:
        return math.nan
    kind = spec.kind
    if kind is Kind.DELTA_T:
        other = traces.get(spec.source2)
        if other is None or other.empty:
            return math.nan
        return other.first_crossing(spec.level2) - tr.first_crossing(spec.level)
    if kind is Kind.TIME_AT_LEVEL:
        return tr.first_crossing(spec.level)
    if kind is Kind.EDGE_COUNT:
        return float(tr.crossings(spec.level).size)
    if kind is Kind.AMPLITUDE:
        return tr.amplitude
    if kind is Kind.BASE:
        return tr.base_top[0]
    if kind is Kind.TOP:
        return tr.base_top[1]
    if kind is Kind.MAXIMUM:
        return float(tr.v.max())
    if kind is Kind.MINIMUM:
        return float(tr.v.min())
    if kind is Kind.PK_PK:
        return float(tr.v.max() - tr.v.min())
    if kind is Kind.MEAN:
        return float(tr.v.mean(dtype=np.float64))
    if kind is Kind.AREA:
        base = tr.base_top[0]
        return (float(tr.v.sum(dtype=np.float64)) - base * tr.v.size) * tr.dt
    if kind is Kind.RISE_TIME:
        return _rise_time(tr)
    if kind is Kind.FALL_TIME:
        return _fall_time(tr)
    if kind is Kind.WIDTH:
        return _width(tr)
    if kind is Kind.PERIOD:
        return _period(tr)
    if kind is Kind.FREQUENCY:
        return 1 / _period(tr)
    if kind is Kind.DUTY_CYCLE:
        return _duty_cycle(tr)
    raise ValueError(f"unknown measurement {kind}")


def measure_all(
    specs: list[MeasurementSpec],
    waveforms: dict[str, Waveform],
    gate: tuple[float, float] | None = None,
) -> list[float]:
    """Values of all measurements for one acquisition; reference levels are computed once."""
    traces = {name: Trace(wf, gate) for name, wf in waveforms.items()}
    with np.errstate(divide="ignore", invalid="ignore"):
        return [measure(spec, traces) for spec in specs]


# --- statistics ------------------------------------------------------------------------------


class Statistics:
    """Last ``HISTORY`` values of one measurement, one per acquisition (NaN = not measured)."""

    def __init__(self, capacity: int = HISTORY):
        self._buffer = np.full(capacity, np.nan)
        self._next = 0
        self._size = 0

    def add(self, value: float) -> None:
        self._buffer[self._next] = value
        self._next = (self._next + 1) % self._buffer.size
        self._size = min(self._size + 1, self._buffer.size)

    def clear(self) -> None:
        self._next = self._size = 0

    @property
    def size(self) -> int:
        """Acquisitions recorded, measured or not."""
        return self._size

    def history(self) -> np.ndarray:
        """All recorded values, oldest first, NaN where the measurement failed."""
        if self._size < self._buffer.size:
            return self._buffer[: self._size].copy()
        return np.concatenate([self._buffer[self._next :], self._buffer[: self._next]])

    def values(self) -> np.ndarray:
        h = self.history()
        return h[np.isfinite(h)]

    @property
    def last(self) -> float:
        return float(self._buffer[self._next - 1]) if self._size else math.nan

    def summary(self) -> "Summary":
        values = self.values()
        if not values.size:
            return Summary(self.last, math.nan, math.nan, math.nan, math.nan, 0, self._size)
        return Summary(
            last=self.last,
            mean=float(values.mean()),
            std=float(values.std(ddof=1)) if values.size > 1 else 0.0,
            minimum=float(values.min()),
            maximum=float(values.max()),
            count=values.size,
            missed=self._size - values.size,
        )


@dataclass(frozen=True)
class Summary:
    last: float
    mean: float
    std: float
    minimum: float
    maximum: float
    count: int
    missed: int


class RangeMode(Enum):
    AUTO_ROBUST = "Auto"
    FULL = "Full"
    MANUAL = "Manual"


ROBUST_SPAN = 8.0  # automatic histogram range: median +- this many robust sigma


def _non_empty(low: float, high: float) -> tuple[float, float]:
    if high > low:
        return low, high
    pad = abs(low) * 0.05 or 1.0  # constant values: a range around them, not an empty one
    return low - pad, low + pad


def histogram_range(
    values: np.ndarray, mode: RangeMode, manual: tuple[float, float] | None = None
) -> tuple[float, float]:
    """(low, high) of a histogram of ``values`` (research R6); never empty.

    ``AUTO_ROBUST`` is the median +- 8 robust sigma (MAD-based), limited to the data, so tails
    and outliers (dark counts, mis-triggers) do not squeeze the main peak into one bin; it falls
    back to min-max when the MAD is 0. ``FULL`` is min-max, ``MANUAL`` the given (from, to).
    """
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if mode is RangeMode.MANUAL and manual is not None:
        return _non_empty(*sorted(manual))
    if not values.size:
        return 0.0, 1.0
    low, high = float(values.min()), float(values.max())
    if mode is RangeMode.AUTO_ROBUST:
        centre = float(np.median(values))
        sigma = _rms(values, centre)
        if sigma > 0:
            low, high = (
                max(low, centre - ROBUST_SPAN * sigma),
                min(high, centre + ROBUST_SPAN * sigma),
            )
    return _non_empty(low, high)


@dataclass(frozen=True)
class GaussFit:
    mean: float
    sigma: float
    amplitude: float  # counts at the peak

    @property
    def fwhm(self) -> float:
        return FWHM_PER_SIGMA * self.sigma

    def __call__(self, x):
        return self.amplitude * np.exp(-0.5 * ((x - self.mean) / self.sigma) ** 2)


def gauss_fit(centers: np.ndarray, counts: np.ndarray, iterations: int = 50) -> GaussFit | None:
    """Gaussian fitted to the highest peak of a histogram.

    Start: the highest peak and its half-maximum width in the histogram smoothed just enough to
    hold ~50 counts around the peak (in a sparse histogram the highest bin is mostly noise).
    Then refined with the moments of the counts within ±2 σ of the current estimate, corrected
    for that cut and for the bin width: unlike a parabola on log counts it is not thrown by empty
    or single-count bins, and the window keeps it on the main peak, ignoring tails and
    neighbouring peaks (e.g. one photoelectron peak of a SiPM spectrum).
    """
    counts = np.asarray(counts, dtype=float)
    if centers.size < 3 or counts.sum() < 10:
        return None
    width = float(centers[1] - centers[0])
    span = float(centers[-1] - centers[0])
    mean, sigma = _peak_start(centers, counts, width)
    for _ in range(iterations):
        half = max(2 * sigma, 1.5 * width)
        window = np.abs(centers - mean) <= half
        x, y = centers[window], counts[window]
        n = float(y.sum())
        if np.count_nonzero(y) < 3 or n < 10:
            return None  # a peak in one or two bins cannot be fitted
        new_mean = float((x * y).sum() / n)
        variance = float(((x - new_mean) ** 2 * y).sum() / n) - width**2 / 12  # Sheppard
        k = half / sigma
        inside = math.erf(k / math.sqrt(2))  # fraction of a Gaussian within ±k σ
        kept = 1 - 2 * k * math.exp(-k * k / 2) / math.sqrt(2 * math.pi) / inside
        new_sigma = math.sqrt(max(variance, width**2 / 100) / kept)
        done = abs(new_mean - mean) < 1e-4 * sigma and abs(new_sigma - sigma) < 1e-4 * sigma
        mean, sigma = new_mean, new_sigma
        if not (centers[0] <= mean <= centers[-1] and sigma <= span / 2):
            return None  # flat or nearly flat: there is no peak
        if done:
            break
    low, high = centers[0] - width / 2, centers[-1] + width / 2
    if mean - 2 * sigma < low and mean + 2 * sigma > high:
        return None  # wider than the histogram on both sides: flat, not a peak
    inside = math.erf(max(2 * sigma, 1.5 * width) / sigma / math.sqrt(2))
    amplitude = n / inside * width / (sigma * math.sqrt(2 * math.pi))
    return GaussFit(mean, sigma, amplitude)


def _peak_start(centers: np.ndarray, counts: np.ndarray, width: float) -> tuple[float, float]:
    """(mean, sigma) of the highest peak, from the histogram smoothed by a Gaussian of ``k``
    bins, the smallest k in 0, 1, 2, 4 ... that puts ~50 counts under the peak."""
    for k in (0, 1, 2, 4, 8, 16):
        if k:
            taps = np.exp(-0.5 * (np.arange(-3 * k, 3 * k + 1) / k) ** 2)
            smooth = np.convolve(counts, taps / taps.sum(), mode="same")
        else:
            smooth = counts
        peak = int(np.argmax(smooth))
        if smooth[peak] * max(1.0, 2.5 * k) >= 50:
            break
    below = smooth < smooth[peak] / 2
    left = peak - (np.flatnonzero(below[:peak][::-1])[:1].tolist() or [peak])[0]
    right = peak + (np.flatnonzero(below[peak:])[:1].tolist() or [counts.size - peak])[0]
    sigma = (right - left) * width / FWHM_PER_SIGMA
    sigma = math.sqrt(max(sigma**2 - (k * width) ** 2, width**2))  # remove the smoothing
    return float(centers[peak]), sigma
