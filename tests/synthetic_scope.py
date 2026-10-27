"""Synthetic WR610Zi for tests and the bench launcher. Test-only (Constitution I/IV).

Models a running scope (Constitution v2.1.0 Principle IV): in AUTO/NORM the newest acquisition
advances with time at ``rate_hz`` and every ``Cn:WF?`` returns the newest one, so channels read
one after another come from different triggers, as on the real WR610Zi. ``ARM`` / ``TRMD SINGLE``
arm one acquisition (``TRMD?`` answers SINGLE until it completes, then STOP; all channels then
share one trigger time); ``FRTR`` completes an armed acquisition at once and does nothing
otherwise; ``TRMD <AUTO|NORM|SINGLE|STOP>`` sets the mode. Replies are real ``WF? ALL`` blocks
(8-bit codes, clipped like the scope). ``on_demand=True`` keeps the old 002 behaviour (a fresh
acquisition on every ``WF? DESC``, paced to ``rate_hz``, mode ignored) for tests that need one
deterministic acquisition per update; it is a test convenience, not a model of the scope.

Default scene (trigger on the C1 clock edge at t = 0):

- C1: 10 MHz clock, 0 -> 2.5 V, ~1 ns edges, 15 ps jitter.
- C2: SiPM A, positive pulses. Poisson(3) photoelectrons x 20 mV (10 % gain spread), rise 1 ns,
  decay 30 ns, arriving at 35 ns (70 ps jitter), plus 1-pe dark counts at 1 MHz and 1.2 mV noise
  band-limited to 1 GHz.
- C3: SiPM B, same but negative and arriving at 37 ns (90 ps jitter).
- C4: NIM discriminator on C2: -0.8 V for 20 ns, 8 ns after the C2 signal crosses 30 mV
  (30 ps jitter).
"""

import copy
import math
import time
from dataclasses import dataclass, field

import numpy as np
from fakes import _timeout_error, build_wavedesc
from pyvisa import constants
from pyvisa.errors import VisaIOError

CHANNEL_INDEX = {"C1": 0, "C2": 1, "C3": 2, "C4": 3}
CODES_PER_DIV = 25  # 8-bit codes: +-127 codes span +-5.08 div, like the WR610Zi
CODE_MIN, CODE_MAX = -128, 127
DESCRIPTOR_LENGTH = 346  # bytes of WAVEDESC


@dataclass
class ChannelSetup:
    volts_per_div: float
    offset: float  # screen centre = -offset volts
    enabled: bool = True
    coupling: str = "D50"


def default_channels() -> dict[str, ChannelSetup]:
    return {
        "C1": ChannelSetup(1.0, -0.25),
        "C2": ChannelSetup(0.020, -0.060),
        "C3": ChannelSetup(0.020, 0.060),
        "C4": ChannelSetup(0.5, 1.0),
    }


@dataclass
class Scene:
    # Acquisition
    time_per_div: float = 50e-9
    trigger_delay: float = -150e-9  # screen centre at +150 ns: trigger 2 div from the left
    points: int = 10_000
    bandwidth: float = 1e9  # front-end bandwidth: noise is correlated over ~0.35/bandwidth
    # C1: clock
    clock_period: float = 100e-9
    clock_high: float = 2.5
    clock_jitter: float = 15e-12
    clock_noise: float = 0.02  # V rms
    edge_time: float = 1e-9  # 10-90 % of the clock and NIM edges
    # C2 / C3: SiPM A (positive) and B (negative)
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
    sipm_noise: float = 1.2e-3  # V rms
    # C4: NIM discriminator on the SiPM A signal
    discriminator: float = 0.030
    nim_delay: float = 8e-9
    nim_width: float = 20e-9
    nim_level: float = -0.8
    nim_jitter: float = 30e-12
    nim_noise: float = 0.01  # V rms
    channels: dict[str, ChannelSetup] = field(default_factory=default_channels)

    @property
    def t0(self) -> float:
        """Time of the first sample: the record covers the 10 divisions on screen."""
        return -self.trigger_delay - 5 * self.time_per_div

    @property
    def dt(self) -> float:
        return 10 * self.time_per_div / self.points


def fit_vertical_scale(scene: Scene) -> Scene:
    """Set C2/C3 to a V/div (1-2-5 steps) at which ``mean_pe`` + 3 sigma photoelectrons stay
    on the 8-bit range, with the baseline 3 divisions off centre as in the default scene.

    The default 20 mV/div suits the default 3 photoelectrons; with a larger ``mean_pe`` the
    pulses would clip and a percent level would sit on the clipped top (a real effect, see the
    spec's edge cases). Returns ``scene`` (modified in place) for chaining.
    """
    peak = scene.pe_volts * (scene.mean_pe + 3 * math.sqrt(scene.mean_pe))
    needed = peak / (CODE_MAX / CODES_PER_DIV + 3)  # baseline 3 div below centre
    decade = 10 ** math.floor(math.log10(needed))
    volts_per_div = next(m * decade for m in (1, 2, 5, 10) if m * decade >= needed)
    volts_per_div = max(volts_per_div, scene.channels["C2"].volts_per_div)
    scene.channels["C2"].volts_per_div = scene.channels["C3"].volts_per_div = volts_per_div
    scene.channels["C2"].offset = -3 * volts_per_div
    scene.channels["C3"].offset = 3 * volts_per_div
    return scene


def _edge(t: np.ndarray, at: float, edge_time: float) -> np.ndarray:
    """Smooth 0 -> 1 step at ``at`` with a 10-90 % time of ``edge_time``."""
    return 0.5 * (1 + np.tanh((t - at) * (2 * math.atanh(0.8) / edge_time)))


def _band_limited(white: np.ndarray, rise_samples: float) -> np.ndarray:
    """Unit-rms white noise smoothed to a 10-90 % rise of ``rise_samples`` (rms stays 1)."""
    sigma = rise_samples / 2.56  # Gaussian filter: 10-90 % rise = 2.56 sigma
    if sigma < 0.5:
        return white
    k = np.arange(-math.ceil(4 * sigma), math.ceil(4 * sigma) + 1)
    weights = np.exp(-0.5 * (k / sigma) ** 2)
    weights /= weights.sum()
    return np.convolve(white, weights, mode="same") / math.sqrt(np.sum(weights**2))


def sipm_pulse(t: np.ndarray, at: float, amplitude: float, rise: float, decay: float):
    """Double-exponential pulse starting at ``at`` with peak ``amplitude``."""
    peak_t = rise * decay / (decay - rise) * math.log(decay / rise)
    norm = math.exp(-peak_t / decay) - math.exp(-peak_t / rise)
    out = np.zeros_like(t)
    first = int(np.searchsorted(t, at))
    s = t[first:] - at
    out[first:] = amplitude / norm * (np.exp(-s / decay) - np.exp(-s / rise))
    return out


class SyntheticAcquisition:
    """One trigger: volts per channel plus the true values the scene was built from.

    ``scene`` is a snapshot: later changes to the scope's scene do not alter this acquisition.
    The true values are ``npe_a``/``npe_b`` (signal photoelectrons), ``arrival_a``/``arrival_b``
    (onset of the signal pulses, jitter included) and ``fired`` (the discriminator saw the
    signal of SiPM A cross its level; dark counts and noise are not seen by it, so ``fired`` is
    false whenever ``npe_a == 0``). ``nim_start`` is the NIM pulse start, ``None`` if not fired.
    """

    def __init__(self, scene: Scene, rng: np.random.Generator):
        sc = self.scene = copy.deepcopy(scene)
        t = sc.t0 + np.arange(sc.points) * sc.dt
        self.times = t
        first, last = float(t[0]), float(t[-1])

        # C1: clock, triggered on its rising edge at t = 0.
        phase = rng.normal(0, sc.clock_jitter)
        n_first = math.floor(first / sc.clock_period) - 1
        rising = np.arange(n_first, last / sc.clock_period + 1)
        c1 = np.zeros_like(t)
        for k in rising * sc.clock_period + phase:
            c1 += _edge(t, k, sc.edge_time) - _edge(t, k + sc.clock_period / 2, sc.edge_time)
        c1 *= sc.clock_high

        def sipm(arrival: float, jitter: float):
            npe = int(rng.poisson(sc.mean_pe))
            at = arrival + rng.normal(0, jitter)
            amplitude = sc.pe_volts * (npe + math.sqrt(npe) * sc.gain_spread * rng.normal())
            signal = sipm_pulse(t, at, amplitude, sc.rise, sc.decay)
            v = signal.copy()
            # Dark counts also start before the record, their tails reach into it.
            window_start = first - 5 * sc.decay
            n_dark = rng.poisson(sc.dark_rate * (last - window_start))
            for dark in rng.uniform(window_start, last, n_dark):
                amp = sc.pe_volts * (1 + sc.gain_spread * rng.normal())
                v += sipm_pulse(t, dark, amp, sc.rise, sc.decay)
            return signal, v, npe, at

        signal_a, c2, self.npe_a, self.arrival_a = sipm(sc.arrival_a, sc.jitter_a)
        signal_b, c3, self.npe_b, self.arrival_b = sipm(sc.arrival_b, sc.jitter_b)
        c3 = -c3

        # C4: NIM logic pulse fired when the A signal crosses the discriminator level.
        c4 = np.zeros_like(t)
        above = np.flatnonzero(signal_a >= sc.discriminator)
        self.fired = above.size > 0
        self.nim_start: float | None = None
        if self.fired:
            i = int(above[0])
            crossing = t[i]
            if i > 0:  # linear interpolation between the samples around the crossing
                lo, hi = signal_a[i - 1], signal_a[i]
                crossing = t[i - 1] + (sc.discriminator - lo) / (hi - lo) * sc.dt
            self.nim_start = float(crossing + sc.nim_delay + rng.normal(0, sc.nim_jitter))
            c4 = sc.nim_level * (
                _edge(t, self.nim_start, sc.edge_time)
                - _edge(t, self.nim_start + sc.nim_width, sc.edge_time)
            )

        def noise(rms: float) -> np.ndarray:
            return rms * _band_limited(rng.normal(size=t.size), 0.35 / sc.bandwidth / sc.dt)

        c1 += noise(sc.clock_noise)
        c2 += noise(sc.sipm_noise)
        c3 += noise(sc.sipm_noise)
        c4 += noise(sc.nim_noise)
        self.volts = {"C1": c1, "C2": c2, "C3": c3, "C4": c4}


def quantize(volts: np.ndarray, setup: ChannelSetup) -> tuple[np.ndarray, float]:
    """8-bit codes of ``volts`` as the scope digitises them, and the volts per code (gain)."""
    gain = float(np.float32(setup.volts_per_div / CODES_PER_DIV))
    codes = np.clip(np.round((volts + setup.offset) / gain), CODE_MIN, CODE_MAX).astype(np.int8)
    return codes, gain


def acquisition_block(
    acq: SyntheticAcquisition, channel: str, kind: str = "ALL", trigger_seconds: float = 0.0
) -> bytes:
    """The reply of ``Cn:WF? <kind>`` for ``acq``: SHORT header + definite-length block."""
    sc = acq.scene
    setup = sc.channels[channel]
    codes, gain = quantize(acq.volts[channel], setup)
    raw = build_wavedesc(
        codes=codes,
        gain=gain,
        offset=setup.offset,
        h_interval=sc.dt,
        h_offset=sc.t0,
        trigger_seconds=trigger_seconds,
        source=CHANNEL_INDEX[channel],
        header=f"{channel}:WF {kind},".encode(),
    )
    if kind == "DESC":  # descriptor only: drop the sample array, keep the block well-formed
        start = raw.index(b"#") + 11
        payload = raw[start : start + DESCRIPTOR_LENGTH]
        raw = f"{channel}:WF DESC,#9{len(payload):09d}".encode() + payload + b"\n"
    return raw


class SyntheticScope:
    """VISA-resource stand-in (write/read_raw/query/clear/close) producing synthetic signals.

    Like ``FakeVisaResource`` it records every written command in ``sent`` (control commands
    ``ARM``/``FRTR``/``TRMD <mode>`` also in ``controls``); a command without a reply times out,
    and control commands never reply. ``reset`` makes every write raise a socket reset (cable
    unplugged).

    Triggers fall on a fixed grid, trigger ``n`` at ``n / rate_hz`` s after the scope was made
    (that ``n / rate_hz`` is the acquisition's trigger time). Acquisitions are generated lazily:
    triggers nobody reads only advance the newest index. ``triggers=False`` keeps an armed
    acquisition from completing by itself (only ``FRTR`` completes it). Time comes from
    ``clock`` (``time.monotonic``); tests may replace it with a controllable one.
    """

    def __init__(
        self,
        scene: Scene | None = None,
        rate_hz: float = 20.0,
        seed: int | None = None,
        trigger_mode: str = "NORM",
        triggers: bool = True,
        on_demand: bool = False,
    ):
        self.scene = scene or Scene()
        self.rate_hz = rate_hz
        self.rng = np.random.default_rng(seed)
        self.timeout = 3000
        self.closed = False
        self.reset = False
        self.trigger_mode = trigger_mode
        self.triggers = triggers
        self.on_demand = on_demand
        self.sent: list[str] = []
        self.controls: list[str] = []
        self.cleared = 0
        self.acquisitions = 0
        self.current: SyntheticAcquisition | None = None
        self.armed_due: float | None = None  # clock time the armed acquisition completes
        self.clock = time.monotonic
        self._origin = self.clock() - 1 / rate_hz  # trigger 1 is due when the scope is made
        self._index = 0  # trigger index of ``current``
        self._armed_index = 0
        self._trigger_seconds = 0.0
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
        """On demand: a new acquisition, no faster than ``rate_hz`` (the wait stands in for
        transfer)."""
        now = time.monotonic()
        if now < self._next_due:
            time.sleep(self._next_due - now)
        self._next_due = max(now, self._next_due) + 1 / self.rate_hz
        self.current = SyntheticAcquisition(self.scene, self.rng)
        self.acquisitions += 1
        # One trigger time per acquisition, shared by all its channels, increasing with 1/rate.
        self._trigger_seconds = self.acquisitions / self.rate_hz

    # --- running model ---------------------------------------------------------------------
    def _newest(self) -> int:
        """Index of the newest trigger that has happened by now."""
        return math.floor((self.clock() - self._origin) * self.rate_hz + 1e-9)

    def _hold(self, index: int) -> None:
        """Generate the acquisition of trigger ``index`` and keep it as the current one."""
        self.current = SyntheticAcquisition(self.scene, self.rng)
        self.acquisitions += 1
        self._index = index
        self._trigger_seconds = index / self.rate_hz

    def _settle(self) -> None:
        """Complete the armed acquisition if its trigger is due."""
        if self.trigger_mode == "SINGLE" and self.triggers and self.armed_due is not None:
            if self.clock() >= self.armed_due:
                self._complete(self._armed_index)

    def _complete(self, index: int) -> None:
        self._hold(index)
        self.armed_due = None
        self.trigger_mode = "STOP"

    def _arm(self) -> None:
        self.trigger_mode = "SINGLE"
        self._armed_index = max(self._newest(), self._index) + 1
        self.armed_due = self._origin + self._armed_index / self.rate_hz

    def _force(self) -> None:
        if self.trigger_mode == "SINGLE" and self.armed_due is not None:
            self._complete(max(self._newest(), self._index + 1))

    def _set_mode(self, mode: str) -> None:
        if mode == "SINGLE":
            self._arm()
            return
        if mode == "STOP" and self.trigger_mode in ("AUTO", "NORM"):
            self._acquisition()  # what was running is what stays held
        self.armed_due = None
        self.trigger_mode = mode

    def _acquisition(self) -> SyntheticAcquisition:
        """What a ``WF?`` answers now: the newest acquisition while running, else the held one."""
        if self.on_demand and self.current is not None:
            return self.current  # made by ``_acquire``: the mode is ignored
        running = self.trigger_mode in ("AUTO", "NORM")
        if self.current is None or (running and self._newest() > self._index):
            self._hold(max(self._newest(), self._index))
        return self.current

    def _control(self, command: str) -> bool:
        """Apply ``ARM`` / ``FRTR`` / ``TRMD <mode>``; False if ``command`` is none of them."""
        verb, _, argument = command.partition(" ")
        if verb == "ARM" and not argument:
            self._arm()
        elif verb == "FRTR" and not argument:
            self._force()
        elif verb == "TRMD" and argument in ("AUTO", "NORM", "SINGLE", "STOP"):
            self._set_mode(argument)
        else:
            return False
        self.controls.append(command)
        return True

    # --- VISA-like API ---------------------------------------------------------------------
    def write(self, command: str) -> None:
        if self.closed:
            raise VisaIOError(constants.StatusCode.error_connection_lost)
        if self.reset:
            raise ConnectionResetError(10054, "connection forcibly closed by the remote host")
        self.sent.append(command)
        self._pending = None
        self._settle()
        ch, _, rest = command.partition(":")
        if rest == "WF? DESC" and ch in CHANNEL_INDEX:
            if self.on_demand:
                self._acquire()
            self._pending = acquisition_block(
                self._acquisition(), ch, "DESC", self._trigger_seconds
            )
        elif rest == "WF? ALL" and ch in CHANNEL_INDEX:
            if self.on_demand and self.current is None:
                self._acquire()
            self._pending = acquisition_block(self._acquisition(), ch, "ALL", self._trigger_seconds)
        elif self._control(command):
            pass  # control commands have no reply
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
        self.cleared += 1
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
