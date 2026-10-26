"""Value objects shared between the driver, the worker thread and the GUI.

See specs/001-live-waveform-view/data-model.md.
"""

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

CHANNELS = ("C1", "C2", "C3", "C4")

# WaveRunner Zi default trace colours (research R10).
CHANNEL_COLORS = {
    "C1": "#F5E400",
    "C2": "#FF5FAF",
    "C3": "#3FC8F0",
    "C4": "#40D040",
}

H_DIVISIONS = 10
V_DIVISIONS = 8
Y_RANGE_DIV = (-V_DIVISIONS / 2, V_DIVISIONS / 2)

SUPPORTED_MODELS = {"WR610ZI"}


class ConnectionState(Enum):
    DISCONNECTED = "Disconnected"
    CONNECTING = "Connecting"
    CONNECTED = "Connected"
    LOST = "Lost"
    ERROR = "Error"


class InstrumentSupport(Enum):
    SUPPORTED = "supported"
    UNTESTED_LECROY = "untested LeCroy model"
    NOT_LECROY = "not a LeCroy oscilloscope"


class TriggerMode(Enum):
    AUTO = "Auto"
    NORM = "Normal"
    SINGLE = "Single"
    STOP = "Stopped"


class AcqState(Enum):
    ACQUIRING = "Acquiring"
    WAITING_FOR_TRIGGER = "Waiting for trigger"
    STOPPED = "Stopped"


@dataclass(frozen=True)
class InstrumentIdentity:
    manufacturer: str
    model: str
    serial: str
    firmware: str

    @property
    def support(self) -> InstrumentSupport:
        return classify_support(self)


def classify_support(identity: InstrumentIdentity) -> InstrumentSupport:
    """LECROY + WR610ZI is supported; other LeCroy models are untested (research R11)."""
    if identity.manufacturer.upper() != "LECROY":
        return InstrumentSupport.NOT_LECROY
    if identity.model.upper() in SUPPORTED_MODELS:
        return InstrumentSupport.SUPPORTED
    return InstrumentSupport.UNTESTED_LECROY


@dataclass(frozen=True)
class ChannelSettings:
    name: str
    enabled: bool
    volts_per_div: float  # > 0
    offset: float  # screen centre = -offset volts
    coupling: str

    @property
    def color(self) -> str:
        return CHANNEL_COLORS[self.name]


@dataclass(frozen=True)
class AcquisitionSettings:
    time_per_div: float  # > 0
    trigger_delay: float  # screen centre time = -trigger_delay
    trigger_mode: TriggerMode
    grid_mode: str
    h_divisions: int = H_DIVISIONS
    v_divisions: int = V_DIVISIONS


@dataclass(frozen=True)
class ScopeStatus:
    channels: tuple[ChannelSettings, ...]
    acquisition: AcquisitionSettings
    acq_state: AcqState
    read_at: float

    def channel(self, name: str) -> ChannelSettings:
        return next(ch for ch in self.channels if ch.name == name)

    @property
    def enabled_channels(self) -> tuple[str, ...]:
        return tuple(ch.name for ch in self.channels if ch.enabled)


@dataclass(frozen=True)
class WaveformDescriptor:
    comm_type: str  # "BYTE" or "WORD"
    little_endian: bool
    vertical_gain: float
    vertical_offset: float
    horiz_interval: float
    horiz_offset: float
    point_count: int
    first_valid: int
    last_valid: int
    trigger_time: float
    source: str
    data_offset: int  # byte offset of the sample array within the block payload

    @property
    def bytes_per_sample(self) -> int:
        return 1 if self.comm_type == "BYTE" else 2


@dataclass(frozen=True)
class Waveform:
    channel: str
    volts: np.ndarray = field(repr=False)
    t0: float
    dt: float
    trigger_time: float
    received_at: float
    step: float = 0.0  # volts per digitiser code (descriptor VERTICAL_GAIN); 0 = unknown

    @property
    def times(self) -> np.ndarray:
        return self.t0 + np.arange(self.volts.size) * self.dt


def x_range(acq: AcquisitionSettings) -> tuple[float, float]:
    """Time span of the scope's screen, relative to the trigger (research R6)."""
    centre = -acq.trigger_delay
    half = acq.time_per_div * acq.h_divisions / 2
    return centre - half, centre + half


def volts_to_div(volts, ch: ChannelSettings):
    """Volts to screen divisions; the screen centre (0 div) is -offset volts."""
    return (volts + ch.offset) / ch.volts_per_div


def div_to_volts(div, ch: ChannelSettings):
    return div * ch.volts_per_div - ch.offset
