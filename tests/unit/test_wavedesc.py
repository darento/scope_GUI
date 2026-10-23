import numpy as np
import pytest
from fakes import build_wavedesc, load_c1_wf_all, load_desc

from scope_gui.errors import ScopeProtocolError
from scope_gui.wavedesc import decode_waveform, parse_descriptor, split_block


def test_split_block_with_and_without_header():
    assert split_block(b"C1:WF ALL,#9000000004abcd\n") == b"abcd"
    assert split_block(b"#9000000004abcd") == b"abcd"


def test_split_block_truncated():
    with pytest.raises(ScopeProtocolError):
        split_block(b"#9000000010abc")


def test_real_descriptor_fields():
    desc = parse_descriptor(split_block(load_desc("C1")))
    assert desc.comm_type == "BYTE"
    assert desc.little_endian
    assert desc.source == "C1"
    assert desc.point_count == 10002
    assert desc.first_valid == 0 and desc.last_valid == 10001
    assert desc.vertical_gain == pytest.approx(0.0332093, rel=1e-5)
    assert desc.vertical_offset == pytest.approx(-3.01, rel=1e-6)
    assert desc.horiz_interval == pytest.approx(1e-10, rel=1e-6)
    assert desc.horiz_offset == pytest.approx(-3.16087e-7, rel=1e-5)
    assert desc.data_offset == 346
    assert desc.trigger_time > 1.7e9  # absolute seconds (2026)


def test_real_descriptor_sources():
    for ch in ("C2", "C3", "C4"):
        assert parse_descriptor(split_block(load_desc(ch))).source == ch


def test_decode_real_waveform():
    desc, volts = decode_waveform(load_c1_wf_all())
    assert volts.dtype == np.float32
    assert volts.size == desc.point_count == 10002
    # 1 V/div with -3.01 V offset: the 8-bit range spans about ±4.25 V around +3.01 V.
    assert -1.5 < volts.min() <= volts.max() < 7.5


@pytest.mark.parametrize(
    "word,little", [(False, True), (True, True), (True, False), (False, False)]
)
def test_decode_synthetic_formats(word, little):
    codes = np.array([-100, 0, 1, 50, 100], dtype=np.int16)
    raw = build_wavedesc(codes=codes, word=word, little=little, gain=0.02, offset=-1.0)
    desc, volts = decode_waveform(raw)
    assert desc.comm_type == ("WORD" if word else "BYTE")
    assert desc.little_endian is little
    np.testing.assert_allclose(volts, codes * 0.02 + 1.0, rtol=1e-6)


def test_rejects_non_wavedesc():
    with pytest.raises(ScopeProtocolError):
        decode_waveform(b"#9000000400" + b"X" * 400)


def test_rejects_wrong_template():
    raw = bytearray(build_wavedesc(codes=np.zeros(4, dtype=np.int16)))
    start = raw.index(b"LECROY_2_3")
    raw[start : start + 10] = b"LECROY_9_9"
    with pytest.raises(ScopeProtocolError):
        decode_waveform(bytes(raw))


def test_rejects_length_mismatch():
    raw = build_wavedesc(codes=np.zeros(10, dtype=np.int16))
    # Drop two data bytes but keep the block header consistent.
    payload = split_block(raw)[:-2]
    bad = b"#9" + f"{len(payload):09d}".encode() + payload
    with pytest.raises(ScopeProtocolError):
        decode_waveform(bad)
