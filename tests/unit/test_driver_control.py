import logging

import pytest
from fakes import FakeVisaResource, fake_factory
from pyvisa.errors import VisaIOError

from scope_gui import driver as driver_module
from scope_gui.driver import ALLOWED_COMMANDS, ScopeDriver, is_allowed, is_control_allowed
from scope_gui.errors import CommandNotAllowed, ScopeError, ScopeLost, ScopeProtocolError
from scope_gui.models import TriggerMode

CONTROL = ["ARM", "FRTR", "TRMD AUTO", "TRMD NORM", "TRMD SINGLE", "TRMD STOP"]

NOT_CONTROL = [
    "TRMD",
    "TRMD ",
    "TRMD FOO",
    "TRMD auto",
    "TRMD AUTO ",
    "TRMD AUTO;ARM",
    "arm",
    "frtr",
    "ARM ;*RST",
    "ARM;FRTR",
    "ARM?",
    "FRTR?",
    "C1:VDIV 1",
    "C1:TRA ON",
    "*RST",
    "STOP",
    "WFSU SP,10",
    "CHDR SHORT",
    "",
]

READ_ONLY = [
    "*IDN?",
    "CHDR?",
    "CFMT?",
    "CORD?",
    "WFSU?",
    "TDIV?",
    "TRDL?",
    "TRMD?",
    "GRID?",
    *[f"{ch}:{q}" for ch in ("C1", "C2", "C3", "C4") for q in ("TRA?", "VDIV?", "OFST?", "CPL?")],
    *[f"{ch}:WF? {part}" for ch in ("C1", "C2", "C3", "C4") for part in ("DESC", "ALL")],
]


@pytest.fixture
def connected(monkeypatch):
    monkeypatch.setattr(driver_module, "tcp_precheck", lambda host, timeout=3.0: None)
    fake = FakeVisaResource()
    driver = ScopeDriver(resource_factory=fake_factory(fake))
    driver.connect("TCPIP0::192.168.0.9::inst0::INSTR")
    fake.sent.clear()
    return driver, fake


@pytest.mark.parametrize("command", CONTROL)
def test_control_allowed(command):
    assert is_control_allowed(command)


@pytest.mark.parametrize("command", NOT_CONTROL + READ_ONLY)
def test_not_control_allowed(command):
    assert not is_control_allowed(command)


def test_allowlists_are_disjoint():
    for command in CONTROL + NOT_CONTROL + READ_ONLY:
        assert not (is_allowed(command) and is_control_allowed(command)), command
    assert not any(is_allowed(command) for command in CONTROL)
    assert len(ALLOWED_COMMANDS) == 15  # the read-only list is unchanged


def test_arm_and_force_trigger_write_and_read_nothing(connected):
    driver, fake = connected
    driver.arm()
    driver.force_trigger()
    assert fake.sent == ["ARM", "FRTR"]
    with pytest.raises(VisaIOError):  # no reply is pending, like the real scope
        fake.read_raw()


@pytest.mark.parametrize(
    "reply,mode",
    [
        ("TRMD AUTO", TriggerMode.AUTO),  # CHDR SHORT
        ("TRIG_MODE NORM", TriggerMode.NORM),  # CHDR LONG
        ("STOP", TriggerMode.STOP),  # CHDR OFF
        ("TRMD SINGLE", TriggerMode.SINGLE),
    ],
)
def test_read_trigger_mode(connected, reply, mode):
    driver, fake = connected
    fake.set_reply("TRMD?", reply)
    if " " not in reply:
        driver._header_mode = "OFF"  # as after connecting with CHDR OFF
    assert driver.read_trigger_mode() is mode
    assert fake.sent == ["TRMD?"]


def test_read_trigger_mode_unknown_value(connected):
    driver, fake = connected
    fake.set_reply("TRMD?", "TRMD BOGUS")
    with pytest.raises(ScopeProtocolError):
        driver.read_trigger_mode()


@pytest.mark.parametrize("mode", list(TriggerMode))
def test_restore_trigger_mode_writes_name_and_confirms(connected, mode, caplog):
    driver, fake = connected
    with caplog.at_level(logging.DEBUG, logger="scope_gui.driver"):
        driver.restore_trigger_mode(mode)
    assert fake.sent == [f"TRMD {mode.name}", "TRMD?"]
    assert driver.read_trigger_mode() is mode
    assert (
        "scope_gui.driver",
        logging.INFO,
        f"trigger mode restored to {mode.value}",
    ) in caplog.record_tuples
    assert ("scope_gui.driver", logging.DEBUG, f"write TRMD {mode.name}") in caplog.record_tuples


def test_restore_trigger_mode_logs_normal(connected, caplog):
    driver, _ = connected
    with caplog.at_level(logging.INFO, logger="scope_gui.driver"):
        driver.restore_trigger_mode(TriggerMode.NORM)
    assert "trigger mode restored to Normal" in caplog.messages


def test_restore_trigger_mode_mismatch(connected, caplog):
    driver, fake = connected
    real_write = fake.write

    def write_ignoring_trmd(command):
        real_write(command)
        if command.startswith("TRMD ") and not command.endswith("?"):
            fake.set_reply("TRMD?", "TRMD AUTO")  # the scope did not take it

    fake.write = write_ignoring_trmd
    with caplog.at_level(logging.INFO, logger="scope_gui.driver"):
        with pytest.raises(ScopeProtocolError):
            driver.restore_trigger_mode(TriggerMode.NORM)
    assert not any("restored" in message for message in caplog.messages)


def test_write_logs_at_debug(connected, caplog):
    driver, _ = connected
    with caplog.at_level(logging.DEBUG, logger="scope_gui.driver"):
        driver.arm()
    assert ("scope_gui.driver", logging.DEBUG, "write ARM") in caplog.record_tuples


def test_write_after_disconnect(connected):
    driver, fake = connected
    driver.close()
    with pytest.raises(ScopeError, match="not connected"):
        driver.arm()
    with pytest.raises(ScopeError, match="not connected"):
        driver.restore_trigger_mode(TriggerMode.AUTO)
    assert fake.sent == []


def test_socket_reset_on_write_is_scope_lost(connected):
    driver, fake = connected
    fake.reset = True
    with pytest.raises(ScopeLost):
        driver.arm()
    with pytest.raises(ScopeLost):
        driver.force_trigger()


@pytest.mark.parametrize("command", ["C1:VDIV 1", "TRMD FOO", "*RST", "TDIV?", "arm"])
def test_write_refuses_other_commands_before_the_wire(connected, command):
    driver, fake = connected
    with pytest.raises(CommandNotAllowed):
        driver._write(command)
    assert fake.sent == []


def test_write_refuses_before_connection_check():
    driver = ScopeDriver()
    with pytest.raises(CommandNotAllowed):
        driver._write("*RST")
    with pytest.raises(ScopeError, match="not connected"):
        driver._write("ARM")


def test_queries_still_refuse_control_commands(connected):
    driver, fake = connected
    for command in CONTROL:
        with pytest.raises(CommandNotAllowed):
            driver._query(command)
        with pytest.raises(CommandNotAllowed):
            driver._query_raw(command)
    assert fake.sent == []
