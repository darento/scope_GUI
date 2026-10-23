import pytest
from fakes import fake_factory

from scope_gui.driver import ScopeDriver, is_allowed, parse_float, parse_value
from scope_gui.errors import CommandNotAllowed

ALLOWED = [
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

FORBIDDEN = [
    "C1:VDIV 1",
    "TRMD STOP",
    "*RST",
    "CFMT DEF9,WORD,BIN",
    "WFSU SP,10",
    "INR?",
    "C5:TRA?",
    "C1:TRA? ",
    "c1:tra?",
    "C1:WF? DAT1",
    "ARM",
    "*CAL?",
]


@pytest.mark.parametrize("command", ALLOWED)
def test_allowed(command):
    assert is_allowed(command)


@pytest.mark.parametrize("command", FORBIDDEN)
def test_forbidden_never_reaches_the_wire(command):
    factory = fake_factory()
    driver = ScopeDriver(resource_factory=factory)
    driver._resource = factory("TCPIP0::x::inst0::INSTR", 1000)
    with pytest.raises(CommandNotAllowed):
        driver._query(command)
    with pytest.raises(CommandNotAllowed):
        driver._query_raw(command)
    assert factory.fake.sent == []


@pytest.mark.parametrize(
    "reply,value",
    [
        ("C1:VDIV 1 V", "1"),
        ("C1:VOLT_DIV 1 V", "1"),
        ("1 V", "1"),
        ("TDIV 5E-6 S", "5E-6"),
        ("TRMD AUTO", "AUTO"),
        ("C1:TRA ON", "ON"),
        ("CFMT DEF9,BYTE,BIN", "DEF9,BYTE,BIN"),
        ("MSIZ 2.5E+6 SAMPLE", "2.5E+6"),
    ],
)
def test_parse_value(reply, value):
    assert parse_value(reply) == value


def test_parse_float():
    assert parse_float("TRDL -184E-9 S") == pytest.approx(-184e-9)
