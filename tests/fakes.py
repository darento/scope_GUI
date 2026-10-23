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


def _timeout_error() -> VisaIOError:
    return VisaIOError(constants.StatusCode.error_timeout)


class FakeVisaResource:
    """Replays captured WR610Zi replies; unknown queries time out like the real scope (R4)."""

    def __init__(self, replies=None, *, busy=False, fail_after=None, fail_count=None):
        self.replies = dict(replies if replies is not None else load_replies())
        self.binary = {f"{ch}:WF? DESC": load_desc(ch) for ch in ("C1", "C2", "C3", "C4")}
        self.binary["C1:WF? ALL"] = load_c1_wf_all()
        for ch in ("C2", "C3", "C4"):
            self.binary[f"{ch}:WF? ALL"] = self.binary["C1:WF? ALL"]
        self.timeout = 3000
        self.sent: list[str] = []
        self.cleared = 0
        self.closed = False
        self.busy = busy
        self.fail_after = fail_after  # start failing after this many commands
        self.fail_count = fail_count  # number of consecutive failures (None = forever)
        self._pending: bytes | None = None
        self.trigger_seconds = None  # when set, WF replies carry this TRIGGER_TIME seconds

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
        raw = self.binary[command]
        if self.trigger_seconds is not None:
            raw = with_trigger_seconds(raw, self.trigger_seconds)
        return raw

    # --- VISA-like API ---------------------------------------------------------------------
    def write(self, command: str) -> None:
        if self.closed:
            raise VisaIOError(constants.StatusCode.error_connection_lost)
        if self.busy:
            raise VisaIOError(constants.StatusCode.error_resource_busy)
        self.sent.append(command)
        if self._should_fail():
            self._pending = None
            return
        if command in self.binary:
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
