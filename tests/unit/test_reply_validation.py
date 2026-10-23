"""Replies must belong to their query: the scope shares one reply queue between clients (R13)."""

import pytest
from fakes import FakeVisaResource, as_channel, fake_factory, load_c1_wf_all, load_desc

from scope_gui import driver as driver_module
from scope_gui.driver import ScopeDriver, reply_matches
from scope_gui.errors import ScopeReplyMismatch

ADDRESS = "TCPIP0::192.168.0.9::inst0::INSTR"


@pytest.fixture(autouse=True)
def reachable(monkeypatch):
    monkeypatch.setattr(driver_module, "tcp_precheck", lambda host, timeout=3.0: None)


@pytest.fixture
def connected():
    fake = FakeVisaResource()
    driver = ScopeDriver(resource_factory=fake_factory(fake))
    driver.connect(ADDRESS)
    fake.sent.clear()
    return driver, fake


@pytest.mark.parametrize(
    "command, reply",
    [
        ("C1:TRA?", "C1:TRA ON"),
        ("C1:TRA?", "C1:TRACE ON"),
        ("C2:VDIV?", "C2:VDIV 500E-3 V"),
        ("C2:VDIV?", "C2:VOLT_DIV 500E-3 V"),
        ("C3:OFST?", "C3:OFFSET -1 V"),
        ("C4:CPL?", "C4:COUPLING D50"),
        ("TDIV?", "TIME_DIV 100E-9 S"),
        ("TRDL?", "TRIG_DELAY 0 S"),
        ("TRMD?", "TRIG_MODE AUTO"),
        ("GRID?", "GRID SINGLE"),
        ("CFMT?", "COMM_FORMAT DEF9,BYTE,BIN"),
        ("CORD?", "COMM_ORDER LO"),
        ("WFSU?", "WAVEFORM_SETUP SP,0,NP,0,FP,0,SN,0"),
        ("*IDN?", "*IDN LECROY,WR610ZI,X,9.1.0"),
    ],
)
def test_short_and_long_headers_accepted(command, reply):
    assert reply_matches(command, reply, "SHORT")


@pytest.mark.parametrize(
    "command, reply",
    [
        ("TDIV?", "C1:VDIV 1 V"),  # well-formed but someone else's reply
        ("C1:VDIV?", "C2:VDIV 1 V"),  # right setting, wrong channel
        ("C1:TRA?", "*IDN LECROY,WR610ZI,X,9.1.0"),
        ("TRMD?", ""),
    ],
)
def test_foreign_text_reply_rejected(command, reply):
    assert not reply_matches(command, reply, "SHORT")


def test_binary_headers():
    assert reply_matches("C1:WF? DESC", load_desc("C1"), "SHORT")
    assert reply_matches("C1:WF? ALL", load_c1_wf_all(), "SHORT")
    assert reply_matches("C1:WF? ALL", b"C1:WAVEFORM ALL,#9000", "SHORT")
    assert not reply_matches("C2:WF? DESC", load_desc("C1"), "SHORT")
    assert not reply_matches("C1:WF? DESC", load_c1_wf_all(), "SHORT")  # ALL for DESC
    assert not reply_matches("C1:WF? ALL", b"TDIV 100E-9 S\n", "SHORT")


def test_chdr_off_checks_binary_only():
    assert reply_matches("TDIV?", "1 V", "OFF")
    assert reply_matches("C1:WF? DESC", b"#9000000346WAVEDESC", "OFF")
    assert not reply_matches("C1:WF? DESC", b"1E-9\n", "OFF")


def test_mismatched_setting_raises_and_flushes(connected):
    driver, fake = connected
    fake.set_reply("TDIV?", "C1:VDIV 1 V")
    cleared = fake.cleared
    with pytest.raises(ScopeReplyMismatch):
        driver.read_status()
    assert fake.cleared == cleared + 1


def test_text_reply_to_binary_query_raises(connected):
    driver, fake = connected
    del fake.binary["C1:WF? DESC"]
    fake.set_reply("C1:WF? DESC", "C1:VDIV 1 V")
    with pytest.raises(ScopeReplyMismatch):
        driver.read_descriptor("C1")


def test_wrong_wave_source_raises(connected):
    driver, fake = connected
    # Header says C3, descriptor says C1: refuse rather than plot C1 data as C3.
    fake.binary["C3:WF? DESC"] = b"C3" + load_desc("C1")[2:]
    with pytest.raises(ScopeReplyMismatch):
        driver.read_descriptor("C3")
    fake.binary["C3:WF? ALL"] = as_channel(load_c1_wf_all(), "C3")
    assert driver.read_waveform("C3").channel == "C3"


def test_chdr_off_skips_text_validation():
    fake = FakeVisaResource()
    replies = {k: v.split(" ", 1)[1] if " " in v else v for k, v in fake.replies.items()}
    replies["*IDN?"] = "LECROY,WR610ZI,LCRY3201N55990,9.1.0"
    replies["CHDR?"] = "OFF"
    fake.replies = replies
    driver = ScopeDriver(resource_factory=fake_factory(fake))
    assert driver.connect(ADDRESS).model == "WR610ZI"
    assert driver.read_status().acquisition.grid_mode == "SINGLE"


def test_connect_with_foreign_reply_raises():
    fake = FakeVisaResource()
    fake.foreign_replies = 1
    driver = ScopeDriver(resource_factory=fake_factory(fake))
    with pytest.raises(ScopeReplyMismatch):
        driver.connect(ADDRESS)
    assert not driver.is_open


def test_connect_with_foreign_chdr_reply_raises():
    fake = FakeVisaResource()
    fake.set_reply("CHDR?", "C1:TRA OFF")
    driver = ScopeDriver(resource_factory=fake_factory(fake))
    with pytest.raises(ScopeReplyMismatch):
        driver.connect(ADDRESS)
