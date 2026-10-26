"""Synthetic WR610Zi for tests and the bench launcher. Test-only (Constitution I/IV).

Generates a fresh acquisition every time the worker checks for one (``Cn:WF? DESC``), paced to
``rate_hz``, and answers it with real ``WF? ALL`` blocks (8-bit codes, clipped like the scope).

Default scene (trigger on the C1 clock edge at t = 0):

- C1: 10 MHz clock, 0 -> 2.5 V, ~1 ns edges, 15 ps jitter.
- C2: SiPM A, positive pulses. Poisson(3) photoelectrons x 20 mV, rise 1 ns, decay 30 ns,
  arriving at 35 ns (70 ps jitter), plus 1-pe dark counts at 1 MHz and 1.2 mV noise.
- C3: SiPM B, same but negative and arriving at 37 ns (90 ps jitter).
- C4: NIM discriminator on C2: -0.8 V for 20 ns, 8 ns after C2 crosses 30 mV (30 ps jitter).
"""

import math
import time
from dataclasses import dataclass, field

import numpy as np
from fakes import _timeout_error, build_wavedesc

CHANNEL_INDEX = {"C1": 0, "C2": 1, "C3": 2, "C4": 3}
CODES_PER_DIV = 25  # 8-bit codes: +-127 codes span +-5.08 div, like the WR610Zi


@dataclass
class ChannelSetup:
    volts_per_div: float
    offset: float  # screen centre = -offset volts
    enabled: bool = True
    coupling: str = "D50"


@dataclass
class Scene:
    time_per_div: float = 50e-9
    trigger_delay: float = -150e-9  # screen centre at +150 ns: trigger 2 div from the left
    points: int = 10_000
    clock_period: float = 100e-9
    clock_high: float = 2.5
    clock_jitter: float = 15e-12
    edge_time: float = 1e-9  # 10-90 % of the clock and NIM edges
    mean_pe: float = 3.0
    pe_volts: float = 0.020
    gain_spread: float = 0.10  # relative sigma of one photoelectron's amplitude
    rise: float = 1e-9
    decay: float = 30e-9
    arrival_a: float = 35e-9
    arrival_b: float = 37e-9
    jitter_a: float = 70e-12
    jitter_b: float = 90e-12
    dark_rate: float = 1e6
    sipm_noise: float = 1.2e-3
    bandwidth: float = 1e9  # front-end bandwidth: noise is correlated over ~0.35/bandwidth
    discriminator: float = 0.030
    nim_delay: float = 8e-9
    nim_width: float = 20e-9
    nim_jitter: float = 30e-12
    channels: dict[str, ChannelSetup] = field(
        default_factory=lambda: {
            "C1": ChannelSetup(1.0, -0.25),
            "C2": ChannelSetup(0.020, -0.060),
            "C3": ChannelSetup(0.020, 0.060),
            "C4": ChannelSetup(0.5, 1.0),
        }
    )

    @property
    def t0(self) -> float:
        """Time of the first sample: the record covers the 10 divisions on screen."""
        return -self.trigger_delay - 5 * self.time_per_div

    @property
    def dt(self) -> float:
        return 10 * self.time_per_div / self.points


def _edge(t: np.ndarray, at: float, edge_time: float) -> np.ndarray:
    """Smooth 0 -> 1 step at ``at`` with a 10-90 % time of ``edge_time``."""
    return 0.5 * (1 + np.tanh((t - at) * (2 * math.atanh(0.8) / edge_time)))


def _band_limited(white: np.ndarray, rise_samples: float) -> np.ndarray:
    """White noise smoothed to a rise time of ``rise_samples``, rescaled to unit rms."""
    sigma = rise_samples / 2.56  # Gaussian filter: 10-90 % rise = 2.56 sigma
    if sigma < 0.5:
        return white
    k = np.arange(-math.ceil(4 * sigma), math.ceil(4 * sigma) + 1)
    kernel = np.exp(-0.5 * (k / sigma) ** 2)
    smooth = np.convolve(white, kernel / kernel.sum(), mode="same")
    return smooth / smooth.std()


def sipm_pulse(t: np.ndarray, at: float, amplitude: float, rise: float, decay: float):
    """Double-exponential pulse starting at ``at`` with peak ``amplitude``."""
    peak_t = rise * decay / (decay - rise) * math.log(decay / rise)
    norm = math.exp(-peak_t / decay) - math.exp(-peak_t / rise)
    s = np.clip(t - at, 0, None)
    return amplitude / norm * (np.exp(-s / decay) - np.exp(-s / rise))


class SyntheticAcquisition:
    """One trigger: volts per channel plus the true values the scene was built from."""

    def __init__(self, scene: Scene, rng: np.random.Generator):
        sc = scene
        t = sc.t0 + np.arange(sc.points) * sc.dt
        self.times = t
        span = (t[0], t[-1])

        # C1: clock, triggered on its rising edge at t = 0.
        phase = rng.normal(0, sc.clock_jitter)
        rising = np.arange(math.floor(span[0] / sc.clock_period) - 1, span[1] / sc.clock_period + 1)
        c1 = np.zeros_like(t)
        for k in rising * sc.clock_period + phase:
            c1 += _edge(t, k, sc.edge_time) - _edge(t, k + sc.clock_period / 2, sc.edge_time)
        c1 *= sc.clock_high

        def sipm(arrival: float, jitter: float, sign: float):
            npe = int(rng.poisson(sc.mean_pe))
            at = arrival + rng.normal(0, jitter)
            amplitude = sc.pe_volts * (npe + math.sqrt(npe) * sc.gain_spread * rng.normal())
            v = sipm_pulse(t, at, amplitude, sc.rise, sc.decay)
            for dark in rng.uniform(span[0], span[1], rng.poisson(sc.dark_rate * (t[-1] - t[0]))):
                amp = sc.pe_volts * (1 + sc.gain_spread * rng.normal())
                v += sipm_pulse(t, dark, amp, sc.rise, sc.decay)
            return sign * v, npe, at

        c2, self.npe_a, self.arrival_a = sipm(sc.arrival_a, sc.jitter_a, 1.0)
        c3, self.npe_b, self.arrival_b = sipm(sc.arrival_b, sc.jitter_b, -1.0)

        # C4: NIM logic pulse fired by the noiseless C2 crossing the discriminator level.
        c4 = np.zeros_like(t)
        above = np.flatnonzero(c2 >= sc.discriminator)
        self.fired = above.size > 0
        if self.fired:
            start = t[above[0]] + sc.nim_delay + rng.normal(0, sc.nim_jitter)
            c4 = -0.8 * (_edge(t, start, sc.edge_time) - _edge(t, start + sc.nim_width, sc.edge_time))

        def noise(rms: float) -> np.ndarray:
            return rms * _band_limited(rng.normal(size=t.size), 0.35 / sc.bandwidth / sc.dt)

        c1 += noise(0.02)
        c2 += noise(sc.sipm_noise)
        c3 += noise(sc.sipm_noise)
        c4 += noise(0.01)
        self.volts = {"C1": c1, "C2": c2, "C3": c3, "C4": c4}


class SyntheticScope:
    """VISA-resource stand-in (write/read_raw/query/clear/close) producing synthetic signals."""

    def __init__(self, scene: Scene | None = None, rate_hz: float = 20.0, seed: int | None = None):
        self.scene = scene or Scene()
        self.rate_hz = rate_hz
        self.rng = np.random.default_rng(seed)
        self.timeout = 3000
        self.closed = False
        self.trigger_mode = "NORM"
        self.acquisitions = 0
        self.current: SyntheticAcquisition | None = None
        self._next_due = 0.0
        self._pending: bytes | None = None

    # --- replies ---------------------------------------------------------------------------
    def _text(self, command: str) -> str | None:
        sc = self.scene
        fixed = {
            "*IDN?": "*IDN LECROY,WR610ZI,SYNTHETIC,9.1.0",
            "CHDR?": "CHDR SHORT",
            "CFMT?": "CFMT DEF9,BYTE,BIN",
            "CORD?": "CORD LO",
            "WFSU?": "WFSU SP,0,NP,0,FP,0,SN,0",
            "TDIV?": f"TDIV {sc.time_per_div:.6E} S",
            "TRDL?": f"TRDL {sc.trigger_delay:.6E} S",
            "TRMD?": f"TRMD {self.trigger_mode}",
            "GRID?": "GRID SINGLE",
        }
        if command in fixed:
            return fixed[command]
        ch, _, query = command.partition(":")
        setup = sc.channels.get(ch)
        if setup is None:
            return None
        return {
            "TRA?": f"{ch}:TRA {'ON' if setup.enabled else 'OFF'}",
            "VDIV?": f"{ch}:VDIV {setup.volts_per_div:.6E} V",
            "OFST?": f"{ch}:OFST {setup.offset:.6E} V",
            "CPL?": f"{ch}:CPL {setup.coupling}",
        }.get(query)

    def _acquire(self) -> None:
        """Make a new acquisition, no faster than ``rate_hz`` (the wait stands in for transfer)."""
        now = time.monotonic()
        if now < self._next_due:
            time.sleep(self._next_due - now)
        self._next_due = max(now, self._next_due) + 1 / self.rate_hz
        self.current = SyntheticAcquisition(self.scene, self.rng)
        self.acquisitions += 1

    def _block(self, ch: str, kind: str) -> bytes:
        sc = self.scene
        setup = sc.channels[ch]
        gain = setup.volts_per_div / CODES_PER_DIV
        volts = self.current.volts[ch]
        codes = np.clip(np.round((volts + setup.offset) / gain), -128, 127).astype(np.int8)
        raw = build_wavedesc(
            codes=codes,
            gain=gain,
            offset=setup.offset,
            h_interval=sc.dt,
            h_offset=sc.t0,
            trigger_seconds=(self.acquisitions / self.rate_hz) % 60,
            source=CHANNEL_INDEX[ch],
            header=f"{ch}:WF {kind},".encode(),
        )
        if kind == "DESC":  # descriptor only: drop the sample array, keep the block well-formed
            start = raw.index(b"#") + 11
            payload = raw[start : start + 346]
            raw = f"{ch}:WF DESC,#9{len(payload):09d}".encode() + payload + b"\n"
        return raw

    # --- VISA-like API ---------------------------------------------------------------------
    def write(self, command: str) -> None:
        if self.closed:
            raise ConnectionResetError(10054, "synthetic scope closed")
        ch, _, rest = command.partition(":")
        if rest == "WF? DESC" and ch in CHANNEL_INDEX:
            self._acquire()
            self._pending = self._block(ch, "DESC")
        elif rest == "WF? ALL" and ch in CHANNEL_INDEX:
            if self.current is None:
                self._acquire()
            self._pending = self._block(ch, "ALL")
        else:
            text = self._text(command)
            self._pending = None if text is None else (text + "\n").encode()

    def read_raw(self) -> bytes:
        if self._pending is None:
            raise _timeout_error()
        data, self._pending = self._pending, None
        return data

    def read(self) -> str:
        return self.read_raw().decode().rstrip("\n")

    def query(self, command: str) -> str:
        self.write(command)
        return self.read()

    def clear(self) -> None:
        self._pending = None

    def close(self) -> None:
        self.closed = True


def synthetic_factory(scope: SyntheticScope):
    """``resource_factory`` for ScopeDriver that hands out ``scope``."""

    def factory(address: str, timeout_ms: int):
        scope.closed = False
        scope.timeout = timeout_ms
        return scope

    return factory
