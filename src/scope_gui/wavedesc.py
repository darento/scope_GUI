"""Decoding of LeCroy waveform blocks (WAVEDESC template LECROY_2_3).

Pure functions; no instrument I/O. Field offsets verified against a real WR610Zi capture
(tests/fixtures/c1_wf_all.bin.gz).
"""

import calendar
import struct

import numpy as np

from .errors import ScopeProtocolError
from .models import CHANNELS, WaveformDescriptor

DESCRIPTOR_NAME = b"WAVEDESC"
TEMPLATE_NAME = b"LECROY_2_3"
MIN_DESCRIPTOR_LENGTH = 346


def split_block(raw: bytes) -> bytes:
    """Return the payload of an IEEE 488.2 definite-length block.

    Accepts replies with or without a header such as ``C1:WF ALL,``.
    """
    start = raw.find(b"#")
    if start < 0 or start + 2 > len(raw):
        raise ScopeProtocolError("no binary block in reply")
    try:
        ndigits = int(raw[start + 1 : start + 2])
        length = int(raw[start + 2 : start + 2 + ndigits])
    except ValueError as exc:
        raise ScopeProtocolError("malformed block header") from exc
    begin = start + 2 + ndigits
    payload = raw[begin : begin + length]
    if len(payload) != length:
        raise ScopeProtocolError(f"block truncated: expected {length} bytes, got {len(payload)}")
    return payload


def _trigger_time(payload: bytes, endian: str) -> float:
    seconds, minutes, hours, days, months, year = struct.unpack_from(
        endian + "dBBBBh", payload, 296
    )
    if not (1 <= months <= 12 and 1 <= days <= 31):
        return seconds
    base = calendar.timegm((year, months, days, hours, minutes, 0, 0, 0, 0))
    return base + seconds


def parse_descriptor(payload: bytes) -> WaveformDescriptor:
    if len(payload) < MIN_DESCRIPTOR_LENGTH or not payload.startswith(DESCRIPTOR_NAME):
        raise ScopeProtocolError("block does not start with WAVEDESC")
    if not payload[16:32].startswith(TEMPLATE_NAME):
        raise ScopeProtocolError(f"unsupported template {payload[16:32].rstrip(b'\0')!r}")

    # COMM_ORDER decides the byte order of every following field; it reads the same either way.
    comm_order = struct.unpack_from("<h", payload, 34)[0]
    if comm_order not in (0, 1):
        comm_order = struct.unpack_from(">h", payload, 34)[0]
    little = comm_order == 1
    e = "<" if little else ">"

    def i16(offset):
        return struct.unpack_from(e + "h", payload, offset)[0]

    def i32(offset):
        return struct.unpack_from(e + "i", payload, offset)[0]

    def f32(offset):
        return struct.unpack_from(e + "f", payload, offset)[0]

    comm_type = i16(32)
    if comm_type not in (0, 1):
        raise ScopeProtocolError(f"unknown COMM_TYPE {comm_type}")
    source = i16(344)
    data_offset = i32(36) + i32(40) + i32(48) + i32(52) + i32(56)
    return WaveformDescriptor(
        comm_type="BYTE" if comm_type == 0 else "WORD",
        little_endian=little,
        vertical_gain=f32(156),
        vertical_offset=f32(160),
        horiz_interval=f32(176),
        horiz_offset=struct.unpack_from(e + "d", payload, 180)[0],
        point_count=i32(116),
        first_valid=i32(124),
        last_valid=i32(128),
        trigger_time=_trigger_time(payload, e),
        source=CHANNELS[source] if 0 <= source < len(CHANNELS) else f"SOURCE{source}",
        data_offset=data_offset,
    )


def decode_waveform(raw: bytes) -> tuple[WaveformDescriptor, np.ndarray]:
    """Decode a ``Cn:WF? ALL`` reply into its descriptor and sample values in volts."""
    payload = split_block(raw)
    desc = parse_descriptor(payload)
    wave_array_1 = struct.unpack_from("<i" if desc.little_endian else ">i", payload, 60)[0]
    expected = desc.point_count * desc.bytes_per_sample
    if wave_array_1 != expected:
        raise ScopeProtocolError(
            f"WAVE_ARRAY_1 is {wave_array_1} bytes, expected {expected} for "
            f"{desc.point_count} {desc.comm_type} samples"
        )
    data = payload[desc.data_offset : desc.data_offset + expected]
    if len(data) != expected:
        raise ScopeProtocolError(f"sample data truncated: {len(data)} of {expected} bytes")
    dtype = (
        np.dtype("i1")
        if desc.comm_type == "BYTE"
        else np.dtype("<i2" if desc.little_endian else ">i2")
    )
    codes = np.frombuffer(data, dtype=dtype)
    volts = (codes.astype(np.float32) * np.float32(desc.vertical_gain)) - np.float32(
        desc.vertical_offset
    )
    return desc, volts
