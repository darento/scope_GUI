import numpy as np
import pytest
from fakes import FakeVisaResource, fake_factory, load_c1_wf_all

from scope_gui import driver as driver_module
from scope_gui.driver import ScopeDriver, waveform_timeout_ms
from scope_gui.errors import ScopeProtocolError
from scope_gui.models import AcqState, TriggerMode
from scope_gui.wavedesc import decode_waveform


@pytest.fixture
def connected(monkeypatch):
    monkeypatch.setattr(driver_module, "tcp_precheck", lambda host, timeout=3.0: None)
    fake = FakeVisaResource()
    driver = ScopeDriver(resource_factory=fake_factory(fake))
    driver.connect("TCPIP0::192.168.0.9::inst0::INSTR")
    fake.sent.clear()
    return driver, fake


def test_read_status_from_fixture(connected):
    driver, fake = connected
    status = driver.read_status()
    assert status.enabled_channels == ("C1", "C3", "C4")
    c1 = status.channel("C1")
    assert (c1.volts_per_div, c1.offset, c1.coupling) == (1.0, -3.01, "D1M")
    c3 = status.channel("C3")
    assert c3.volts_per_div == pytest.approx(0.5) and c3.offset == pytest.approx(-0.485)
    acq = status.acquisition
    assert acq.time_per_div == pytest.approx(100e-9)
    assert acq.trigger_delay == pytest.approx(-184e-9)
    assert acq.trigger_mode is TriggerMode.AUTO
    assert acq.grid_mode == "SINGLE"
    assert status.acq_state is AcqState.ACQUIRING
    assert all(cmd.endswith("?") for cmd in fake.sent)


def test_read_status_stopped(connected):
    driver, fake = connected
    fake.set_reply("TRMD?", "TRMD STOP")
    status = driver.read_status()
    assert status.acquisition.trigger_mode is TriggerMode.STOP
    assert status.acq_state is AcqState.STOPPED


def test_read_status_long_headers(connected):
    driver, fake = connected
    fake.set_reply("C1:VDIV?", "C1:VOLT_DIV 2 V")
    fake.set_reply("TRMD?", "TRIG_MODE NORM")
    status = driver.read_status()
    assert status.channel("C1").volts_per_div == 2.0
    assert status.acquisition.trigger_mode is TriggerMode.NORM


def test_read_status_garbage(connected):
    driver, fake = connected
    fake.set_reply("TDIV?", "TDIV ???")
    with pytest.raises(ScopeProtocolError):
        driver.read_status()


def test_read_descriptor_sends_desc_only(connected):
    driver, fake = connected
    desc = driver.read_descriptor("C1")
    assert fake.sent == ["C1:WF? DESC"]
    assert desc.point_count == 10002


def test_read_waveform(connected):
    driver, fake = connected
    driver.read_descriptor("C1")
    wf = driver.read_waveform("C1")
    assert fake.sent[-1] == "C1:WF? ALL"
    assert fake.timeout == waveform_timeout_ms(346 + 10002)
    _, volts = decode_waveform(load_c1_wf_all())
    np.testing.assert_array_equal(wf.volts, volts)
    assert wf.t0 == pytest.approx(-3.16087e-7, rel=1e-5)
    assert wf.dt == pytest.approx(1e-10, rel=1e-6)
    assert wf.times[0] == pytest.approx(wf.t0)


@pytest.mark.parametrize(
    "nbytes,ms", [(0, 2000), (100_000, 2100), (500_348, 2500), (25_000_000, 10000)]
)
def test_waveform_timeout(nbytes, ms):
    assert waveform_timeout_ms(nbytes) == ms


def test_socket_reset_maps_to_scope_lost(connected):
    from scope_gui.errors import ScopeLost

    driver, fake = connected
    fake.reset = True
    with pytest.raises(ScopeLost):
        driver.read_status()
    with pytest.raises(ScopeLost):
        driver.read_waveform("C1")
