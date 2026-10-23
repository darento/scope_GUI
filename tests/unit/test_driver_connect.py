import logging
import time

import pytest
from fakes import FakeVisaResource, fake_factory

from scope_gui import driver as driver_module
from scope_gui.driver import ScopeDriver
from scope_gui.driver import tcp_precheck as real_tcp_precheck
from scope_gui.errors import ScopeBusy, ScopeTimeout, ScopeUnreachable
from scope_gui.models import InstrumentIdentity, InstrumentSupport, classify_support

ADDRESS = "TCPIP0::192.168.0.9::inst0::INSTR"


@pytest.fixture(autouse=True)
def reachable(monkeypatch):
    monkeypatch.setattr(driver_module, "tcp_precheck", lambda host, timeout=3.0: None)


def test_connect_returns_identity_and_logs_setup(caplog):
    factory = fake_factory()
    driver = ScopeDriver(resource_factory=factory)
    with caplog.at_level(logging.INFO, logger="scope_gui.driver"):
        identity = driver.connect(ADDRESS)
    assert identity == InstrumentIdentity("LECROY", "WR610ZI", "LCRY3201N55990", "9.1.0")
    assert identity.support is InstrumentSupport.SUPPORTED
    assert factory.fake.sent == ["*IDN?", "CHDR?", "CFMT?", "CORD?", "WFSU?"]
    assert "DEF9,BYTE,BIN" in caplog.text
    assert driver.is_open


def test_connect_warns_when_wfsu_not_default(caplog):
    fake = FakeVisaResource()
    fake.set_reply("WFSU?", "WFSU SP,10,NP,0,FP,0,SN,0")
    driver = ScopeDriver(resource_factory=fake_factory(fake))
    with caplog.at_level(logging.WARNING, logger="scope_gui.driver"):
        driver.connect(ADDRESS)
    assert "WFSU" in caplog.text


def test_unreachable_is_fast(monkeypatch):
    def fail(host, timeout=3.0):
        raise ScopeUnreachable(f"Instrument not reachable at {host}")

    monkeypatch.setattr(driver_module, "tcp_precheck", fail)
    factory = fake_factory()
    driver = ScopeDriver(resource_factory=factory)
    start = time.monotonic()
    with pytest.raises(ScopeUnreachable):
        driver.connect(ADDRESS)
    assert time.monotonic() - start < 4
    assert factory.fake.sent == []
    assert not driver.is_open


def test_real_precheck_unreachable_port():
    start = time.monotonic()
    with pytest.raises(ScopeUnreachable):
        real_tcp_precheck("127.0.0.1", timeout=1.0)  # nothing listens on 111 locally
    assert time.monotonic() - start < 2


def test_busy():
    driver = ScopeDriver(resource_factory=fake_factory(busy=True))
    with pytest.raises(ScopeBusy):
        driver.connect(ADDRESS)
    assert not driver.is_open


def test_idn_timeout():
    fake = FakeVisaResource()
    del fake.replies["*IDN?"]
    driver = ScopeDriver(resource_factory=fake_factory(fake))
    with pytest.raises(ScopeTimeout):
        driver.connect(ADDRESS)
    assert fake.closed
    assert not driver.is_open


def test_close_is_idempotent():
    factory = fake_factory()
    driver = ScopeDriver(resource_factory=factory)
    driver.connect(ADDRESS)
    driver.close()
    driver.close()
    assert factory.fake.closed
    assert not driver.is_open


def test_recover_clears_and_checks_identity():
    factory = fake_factory()
    driver = ScopeDriver(resource_factory=factory)
    driver.connect(ADDRESS)
    assert driver.recover() is True
    assert factory.fake.cleared == 1
    assert factory.fake.sent[-1] == "*IDN?"
    del factory.fake.replies["*IDN?"]
    assert driver.recover() is False


@pytest.mark.parametrize(
    "idn,support",
    [
        (("LECROY", "WR610ZI"), InstrumentSupport.SUPPORTED),
        (("LECROY", "WAVEPRO"), InstrumentSupport.UNTESTED_LECROY),
        (("KEYSIGHT", "DSOX3024T"), InstrumentSupport.NOT_LECROY),
    ],
)
def test_classify_support(idn, support):
    assert classify_support(InstrumentIdentity(*idn, "SN", "1.0")) is support
