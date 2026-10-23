"""Live loop of the worker against the fake instrument (worker runs in the test's thread)."""

import time

import pytest
from fakes import FakeVisaResource, fake_factory

from scope_gui import driver as driver_module
from scope_gui import worker as worker_module
from scope_gui.driver import ScopeDriver, is_allowed
from scope_gui.models import AcqState, ConnectionState
from scope_gui.worker import AcquisitionWorker


@pytest.fixture(autouse=True)
def reachable(monkeypatch):
    monkeypatch.setattr(driver_module, "tcp_precheck", lambda host, timeout=3.0: None)


class Recorder:
    def __init__(self, worker):
        self.states, self.statuses, self.waveforms, self.rates = [], [], [], []
        worker.state_changed.connect(lambda s, m: self.states.append((s, m)))
        worker.status_updated.connect(self.statuses.append)
        worker.waveforms_updated.connect(self.waveforms.append)
        worker.rate_updated.connect(self.rates.append)


@pytest.fixture
def live(qtbot):
    fake = FakeVisaResource()
    factory = fake_factory(fake)
    worker = AcquisitionWorker(lambda: ScopeDriver(resource_factory=factory))
    rec = Recorder(worker)
    worker.connect_to("192.168.0.9")
    assert worker.state is ConnectionState.CONNECTED
    yield worker, fake, rec, qtbot
    worker.close_connection()


def wf_all(fake):
    return [c for c in fake.sent if c.endswith("WF? ALL")]


def test_first_cycle_transfers_enabled_channels_only(live):
    worker, fake, rec, qtbot = live
    qtbot.waitUntil(lambda: bool(rec.waveforms), timeout=2000)
    assert set(rec.waveforms[0]) == {"C1", "C3", "C4"}
    assert sorted(wf_all(fake)) == ["C1:WF? ALL", "C3:WF? ALL", "C4:WF? ALL"]
    assert rec.statuses[0].acq_state is AcqState.ACQUIRING


def test_no_transfer_when_trigger_time_unchanged(live):
    worker, fake, rec, qtbot = live
    qtbot.waitUntil(lambda: len(rec.statuses) >= 4, timeout=3000)
    assert len(wf_all(fake)) == 3  # only the first acquisition
    assert len(rec.waveforms) == 1


def test_new_trigger_time_triggers_transfer(live):
    worker, fake, rec, qtbot = live
    qtbot.waitUntil(lambda: bool(rec.waveforms), timeout=2000)
    fake.trigger_seconds = 12.5
    qtbot.waitUntil(lambda: len(rec.waveforms) == 2, timeout=2000)
    fake.trigger_seconds = 13.5
    qtbot.waitUntil(lambda: len(rec.waveforms) == 3, timeout=2000)


def test_stopped_scope(live):
    worker, fake, rec, qtbot = live
    qtbot.waitUntil(lambda: bool(rec.waveforms), timeout=2000)
    fake.set_reply("TRMD?", "TRMD STOP")
    qtbot.waitUntil(lambda: rec.statuses[-1].acq_state is AcqState.STOPPED, timeout=2000)
    count = len(wf_all(fake))
    qtbot.wait(600)
    assert len(wf_all(fake)) == count  # never re-reads or restarts acquisition


def test_waiting_for_trigger(live, monkeypatch):
    worker, fake, rec, qtbot = live
    monkeypatch.setattr(worker_module, "WAIT_FOR_TRIGGER_S", 0.3)
    qtbot.waitUntil(lambda: bool(rec.waveforms), timeout=2000)
    fake.set_reply("TRMD?", "TRMD NORM")
    qtbot.waitUntil(
        lambda: rec.statuses[-1].acq_state is AcqState.WAITING_FOR_TRIGGER, timeout=2000
    )
    fake.trigger_seconds = 20.0
    qtbot.waitUntil(lambda: rec.statuses[-1].acq_state is AcqState.ACQUIRING, timeout=2000)


def test_settings_change_and_channel_toggle(live):
    worker, fake, rec, qtbot = live
    qtbot.waitUntil(lambda: bool(rec.waveforms), timeout=2000)
    fake.set_reply("C1:VDIV?", "C1:VDIV 2 V")
    fake.set_reply("C3:TRA?", "C3:TRA OFF")
    qtbot.waitUntil(lambda: rec.statuses[-1].channel("C1").volts_per_div == 2.0, timeout=2000)
    # Enabled set changed -> fresh transfer of the remaining channels.
    qtbot.waitUntil(lambda: len(rec.waveforms) == 2, timeout=2000)
    assert set(rec.waveforms[-1]) == {"C1", "C4"}


def test_single_timeout_is_recovered(live):
    worker, fake, rec, qtbot = live
    qtbot.waitUntil(lambda: bool(rec.statuses), timeout=2000)
    fake.fail_after, fake.fail_count = len(fake.sent), 1
    cleared = fake.cleared
    qtbot.waitUntil(lambda: fake.cleared > cleared, timeout=2000)
    qtbot.wait(500)
    assert worker.state is ConnectionState.CONNECTED


def test_persistent_failure_is_lost_within_5s(live):
    worker, fake, rec, qtbot = live
    qtbot.waitUntil(lambda: bool(rec.statuses), timeout=2000)
    start = time.monotonic()
    fake.fail_after, fake.fail_count = len(fake.sent), None
    qtbot.waitUntil(lambda: worker.state is ConnectionState.LOST, timeout=5000)
    assert time.monotonic() - start < 5
    assert rec.states[-1][1] == "Instrument did not respond (timeout)"
    assert fake.closed


def test_busy_is_retried_then_lost(live, monkeypatch):
    worker, fake, rec, qtbot = live
    monkeypatch.setattr(worker_module, "LOST_AFTER_S", 0.6)
    qtbot.waitUntil(lambda: bool(rec.statuses), timeout=2000)
    fake.busy = True
    qtbot.wait(300)
    assert worker.state is ConnectionState.CONNECTED  # still retrying
    fake.busy = False
    n = len(rec.statuses)
    qtbot.waitUntil(lambda: len(rec.statuses) > n, timeout=2000)  # recovered by itself
    fake.busy = True
    qtbot.waitUntil(lambda: worker.state is ConnectionState.LOST, timeout=3000)


def test_rate_reflects_acquisitions(live):
    worker, fake, rec, qtbot = live
    for i in range(6):
        fake.trigger_seconds = 30.0 + i
        qtbot.waitUntil(lambda i=i: len(rec.waveforms) == i + 2, timeout=2000)
    assert rec.rates[-1] > 0


def test_only_allowlisted_commands_sent(live):
    worker, fake, rec, qtbot = live
    fake.trigger_seconds = 40.0
    qtbot.waitUntil(lambda: len(rec.statuses) >= 3, timeout=3000)
    assert fake.sent and all(is_allowed(cmd) for cmd in fake.sent)


def test_disconnect_stops_loop(live):
    worker, fake, rec, qtbot = live
    qtbot.waitUntil(lambda: bool(rec.statuses), timeout=2000)
    worker.close_connection()
    n = len(fake.sent)
    qtbot.wait(500)
    assert len(fake.sent) == n
    assert worker.state is ConnectionState.DISCONNECTED


def test_cable_unplugged_socket_reset(live):
    """Regression: a socket reset (WinError 10054) must give a short English message."""
    worker, fake, rec, qtbot = live
    qtbot.waitUntil(lambda: bool(rec.statuses), timeout=2000)
    start = time.monotonic()
    fake.reset = True
    qtbot.waitUntil(lambda: worker.state is ConnectionState.LOST, timeout=5000)
    assert time.monotonic() - start < 5
    assert rec.states[-1][1] == "Network link to the scope was interrupted"
