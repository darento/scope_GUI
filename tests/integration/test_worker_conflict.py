"""Another program polling the scope: discard foreign replies, then step back (FR-021)."""

import pytest
from fakes import FakeVisaResource, fake_factory

from scope_gui import driver as driver_module
from scope_gui.driver import ScopeDriver
from scope_gui.models import ConnectionState
from scope_gui.worker import CONFLICT_MESSAGE, AcquisitionWorker


@pytest.fixture(autouse=True)
def reachable(monkeypatch):
    monkeypatch.setattr(driver_module, "tcp_precheck", lambda host, timeout=3.0: None)


@pytest.fixture
def live(qtbot):
    fake = FakeVisaResource()
    worker = AcquisitionWorker(lambda: ScopeDriver(resource_factory=fake_factory(fake)))
    states, statuses = [], []
    worker.state_changed.connect(lambda s, m: states.append((s, m)))
    worker.status_updated.connect(statuses.append)
    worker.waveforms_updated.connect(lambda _w: worker.waveforms_consumed())  # like the GUI
    worker.connect_to("192.168.0.9")
    qtbot.waitUntil(lambda: bool(statuses), timeout=2000)
    yield worker, fake, states, statuses, qtbot
    worker.close_connection()


def test_single_mismatch_is_discarded_and_polling_continues(live):
    worker, fake, states, statuses, qtbot = live
    seen = len(statuses)
    fake.foreign_replies = 1
    qtbot.waitUntil(lambda: len(statuses) >= seen + 3, timeout=3000)
    assert worker.state is ConnectionState.CONNECTED


def test_repeated_mismatches_stop_polling(live):
    worker, fake, states, statuses, qtbot = live
    fake.foreign_replies = 10**6  # another program keeps stealing replies
    qtbot.waitUntil(lambda: worker.state is ConnectionState.LOST, timeout=5000)
    assert states[-1] == (ConnectionState.LOST, CONFLICT_MESSAGE)
    sent = len(fake.sent)
    qtbot.wait(500)
    assert len(fake.sent) == sent  # stopped: no more queries


def test_mismatched_value_never_reaches_the_ui(live):
    worker, fake, states, statuses, qtbot = live
    fake.set_reply("TDIV?", "C1:VDIV 1 V")  # would read as 1 s/div if accepted
    qtbot.waitUntil(lambda: worker.state is ConnectionState.LOST, timeout=5000)
    assert all(s.acquisition.time_per_div == pytest.approx(100e-9) for s in statuses)
    assert states[-1][1] == CONFLICT_MESSAGE


def test_mismatch_then_timeouts_reports_other_program(live):
    """Measured on the real scope: after foreign replies, ours go to the other program."""
    worker, fake, states, statuses, qtbot = live
    fake.foreign_replies = 1
    qtbot.waitUntil(lambda: worker._conflicts == 1, timeout=3000)
    fake.fail_after = len(fake.sent)  # every reply from now on is taken by the other client
    qtbot.waitUntil(lambda: worker.state is ConnectionState.LOST, timeout=5000)
    assert states[-1][1] == CONFLICT_MESSAGE


def test_connect_timeout_hints_at_other_program(qtbot):
    fake = FakeVisaResource(fail_after=0)
    worker = AcquisitionWorker(lambda: ScopeDriver(resource_factory=fake_factory(fake)))
    states = []
    worker.state_changed.connect(lambda s, m: states.append((s, m)))
    worker.connect_to("192.168.0.9")
    assert states[-1] == (
        ConnectionState.ERROR,
        "Instrument did not respond (timeout) - another program may be using the scope",
    )
