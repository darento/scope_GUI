"""Test-only stand-ins for the scope. Never imported by the application (Constitution I/IV)."""

import gzip
import json
import struct
from pathlib import Path

import numpy as np
from pyvisa import constants
from pyvisa.errors import VisaIOError

FIXTURES = Path(__file__).parent / "fixtures"


def load_replies() -> dict[str, str]:
    return json.loads((FIXTURES / "wr610zi_replies.json").read_text())


def load_desc(channel: str) -> bytes:
    return (FIXTURES / f"{channel.lower()}_desc.bin").read_bytes()


def load_c1_wf_all() -> bytes:
    with gzip.open(FIXTURES / "c1_wf_all.bin.gz", "rb") as f:
        return f.read()


def build_wavedesc(
    *,
    codes: np.ndarray,
    word: bool = False,
    little: bool = True,
    gain: float = 0.01,
    offset: float = 0.0,
    h_interval: float = 1e-9,
    h_offset: float = -5e-6,
    trigger_seconds: float = 1.0,
    source: int = 0,
    header: bytes = b"C1:WF ALL,",
) -> bytes:
    """Build a complete ``WF? ALL`` reply with a synthetic LECROY_2_3 descriptor."""
    e = "<" if little else ">"
    desc = bytearray(346)
    desc[0:8] = b"WAVEDESC"
    desc[16:26] = b"LECROY_2_3"
    struct.pack_into(e + "h", desc, 32, 1 if word else 0)
    struct.pack_into(e + "h", desc, 34, 1 if little else 0)
    data = codes.astype((e + "i2") if word else "i1").tobytes()
    struct.pack_into(e + "i", desc, 36, 346)
    struct.pack_into(e + "i", desc, 60, len(data))
    desc[76:89] = b"LECROYWR610Zi"
    struct.pack_into(e + "i", desc, 116, codes.size)
    struct.pack_into(e + "i", desc, 124, 0)
    struct.pack_into(e + "i", desc, 128, codes.size - 1)
    struct.pack_into(e + "f", desc, 156, gain)
    struct.pack_into(e + "f", desc, 160, offset)
    struct.pack_into(e + "f", desc, 176, h_interval)
    struct.pack_into(e + "d", desc, 180, h_offset)
    struct.pack_into(e + "dBBBBh", desc, 296, trigger_seconds, 7, 16, 23, 10, 2026)
    struct.pack_into(e + "h", desc, 344, source)
    payload = bytes(desc) + data
    return header + b"#9" + f"{len(payload):09d}".encode() + payload + b"\n"


def with_trigger_seconds(raw: bytes, seconds: float) -> bytes:
    """Return a copy of a real little-endian WF reply with TRIGGER_TIME seconds replaced."""
    start = raw.index(b"#") + 11
    out = bytearray(raw)
    struct.pack_into("<d", out, start + 296, seconds)
    return bytes(out)


_TIMESTAMP = slice(296, 312)  # TRIGGER_TIME field within the WAVEDESC payload


def _timestamp(raw: bytes) -> bytes:
    start = raw.index(b"#") + 11
    return raw[start + _TIMESTAMP.start : start + _TIMESTAMP.stop]


def with_timestamp(raw: bytes, stamp: bytes) -> bytes:
    start = raw.index(b"#") + 11
    out = bytearray(raw)
    out[start + _TIMESTAMP.start : start + _TIMESTAMP.stop] = stamp
    return bytes(out)


def as_channel(raw: bytes, channel: str) -> bytes:
    """Copy of a little-endian WF reply relabelled as ``channel`` (header, WAVE_SOURCE)."""
    start = raw.index(b"#")
    out = bytearray(channel.encode() + raw[2:])  # "C1:WF ALL,#9..." -> "Cn:WF ALL,#9..."
    struct.pack_into("<h", out, start + 11 + 344, int(channel[1]) - 1)
    return bytes(out)


def _timeout_error() -> VisaIOError:
    return VisaIOError(constants.StatusCode.error_timeout)


class FakeVisaResource:
    """Replays captured WR610Zi replies; unknown queries time out like the real scope (R4)."""

    def __init__(self, replies=None, *, busy=False, fail_after=None, fail_count=None):
        self.replies = dict(replies if replies is not None else load_replies())
        self.binary = {f"{ch}:WF? DESC": load_desc(ch) for ch in ("C1", "C2", "C3", "C4")}
        self.binary["C1:WF? ALL"] = load_c1_wf_all()
        for ch in ("C2", "C3", "C4"):
            self.binary[f"{ch}:WF? ALL"] = as_channel(self.binary["C1:WF? ALL"], ch)
        self.timeout = 3000
        self.sent: list[str] = []
        self.cleared = 0
        self.closed = False
        self.busy = busy
        self.reset = False  # raise a socket reset on every write (cable unplugged)
        self.fail_after = fail_after  # start failing after this many commands
        self.fail_count = fail_count  # number of consecutive failures (None = forever)
        self._pending: bytes | None = None
        self.trigger_seconds = None  # when set, WF replies carry this TRIGGER_TIME seconds
        # Next N queries get the reply meant for another client's *IDN? (like a second program
        # polling the scope through the shared reply queue, research R13).
        self.foreign_replies = 0

    # --- knobs -----------------------------------------------------------------------------
    def set_reply(self, command: str, reply: str) -> None:
        self.replies[command] = reply

    def _should_fail(self) -> bool:
        if self.fail_after is None or len(self.sent) <= self.fail_after:
            return False
        if self.fail_count is None:
            return True
        if self.fail_count > 0:
            self.fail_count -= 1
            return True
        return False

    def _binary(self, command: str) -> bytes:
        # The fixtures were captured at different moments; like the real scope, every reply of
        # one acquisition must carry the same TRIGGER_TIME, so all use the WF? ALL timestamp.
        raw = with_timestamp(self.binary[command], _timestamp(self.binary["C1:WF? ALL"]))
        if self.trigger_seconds is not None:
            raw = with_trigger_seconds(raw, self.trigger_seconds)
        return raw

    # --- VISA-like API ---------------------------------------------------------------------
    def write(self, command: str) -> None:
        if self.closed:
            raise VisaIOError(constants.StatusCode.error_connection_lost)
        if self.reset:
            # What pyvisa-py raised on the lab PC when the Ethernet cable was unplugged.
            raise ConnectionResetError(10054, "connection forcibly closed by the remote host")
        if self.busy:
            raise VisaIOError(constants.StatusCode.error_resource_busy)
        self.sent.append(command)
        if self._should_fail():
            self._pending = None
            return
        if self.foreign_replies > 0:
            self.foreign_replies -= 1
            self._pending = (self.replies["*IDN?"] + "\n").encode()
            if command == "*IDN?":  # stolen identity: hand out another client's setting reply
                self._pending = b"C1:VDIV 1 V\n"
        elif command in self.binary:
            self._pending = self._binary(command)
        elif command in self.replies:
            self._pending = (self.replies[command] + "\n").encode()
        else:
            self._pending = None

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


def fake_factory(resource: FakeVisaResource | None = None, **knobs):
    """Return a ``resource_factory`` for ScopeDriver plus the fake it will hand out."""
    fake = resource or FakeVisaResource(**knobs)

    def factory(address: str, timeout_ms: int):
        if fake.busy:
            raise VisaIOError(constants.StatusCode.error_resource_busy)
        fake.closed = False
        fake.timeout = timeout_ms
        fake.address = address
        return fake

    factory.fake = fake
    return factory
