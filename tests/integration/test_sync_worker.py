"""Synchronized capture in the worker on a running synthetic scope (003 driver-control contract).

The worker runs in the test's thread; ``qtbot.wait*`` lets its timer cycles run.
"""

import logging
import time

import pytest
from synthetic_scope import Scene, SyntheticScope, synthetic_factory

from scope_gui import driver as driver_module
from scope_gui import worker as worker_module
from scope_gui.driver import ScopeDriver, is_allowed, is_control_allowed
from scope_gui.models import AcqState, ConnectionState, TriggerMode
from scope_gui.worker import AcquisitionWorker

SMALL = 2000  # points per record
EXTERNAL = "Trigger mode changed on the scope - synchronized capture switched off"


@pytest.fixture(autouse=True)
def reachable(monkeypatch):
    monkeypatch.setattr(driver_module, "tcp_precheck", lambda host, timeout=3.0: None)


class Recorder:
    def __init__(self, worker, consume=True):
        self.states, self.statuses, self.waveforms, self.rates, self.syncs = [], [], [], [], []
        worker.state_changed.connect(lambda s, m: self.states.append((s, m)))
        worker.status_updated.connect(self.statuses.append)
        worker.waveforms_updated.connect(self.waveforms.append)
        if consume:
            worker.waveforms_updated.connect(lambda _w: worker.waveforms_consumed())
        worker.rate_updated.connect(self.rates.append)
        worker.sync_changed.connect(lambda on, m: self.syncs.append((on, m)))


@pytest.fixture
def bench(qtbot):
    """``bench(mode="AUTO", rate_hz=500, triggers=True, consume=True) -> (worker, scope, rec)``."""
    workers = []

    def make(mode="AUTO", rate_hz=500.0, triggers=True, consume=True):
        scene = Scene(points=SMALL)
        scope = SyntheticScope(scene, rate_hz, 1, trigger_mode=mode, triggers=triggers)
        factory = synthetic_factory(scope)
        worker = AcquisitionWorker(lambda: ScopeDriver(resource_factory=factory))
        rec = Recorder(worker, consume)
        worker.connect_to("synthetic")
        assert worker.state is ConnectionState.CONNECTED
        workers.append(worker)
        return worker, scope, rec

    yield make
    for worker in workers:
        worker.close_connection()


def timed_writes(scope):
    """Record (time, command) of every command the scope receives."""
    log, write = [], scope.write

    def recording(command):
        log.append((time.monotonic(), command))
        write(command)

    scope.write = recording
    return log


def test_off_after_connect_and_ignored_when_not_connected(bench, qtbot):
    worker, scope, rec = bench()
    qtbot.waitUntil(lambda: len(rec.waveforms) >= 2, timeout=3000)
    assert scope.controls == []  # never switched on: nothing written
    assert all(is_allowed(c) for c in scope.sent)
    worker.close_connection()
    worker.set_synchronized(True)
    assert rec.syncs == [] and scope.trigger_mode == "AUTO"


def test_every_set_is_one_trigger_and_rate_counts_them(bench, qtbot):
    worker, scope, rec = bench(rate_hz=2000)
    worker.set_synchronized(True)
    assert rec.syncs == [(True, "")]
    start = len(rec.waveforms)
    qtbot.waitUntil(lambda: len(rec.waveforms) >= start + 10, timeout=5000)
    for waves in rec.waveforms[start:]:
        assert len({w.trigger_time for w in waves.values()}) == 1
        assert set(waves) == {"C1", "C2", "C3", "C4"}
    assert rec.rates[-1] > 0
    assert set(scope.controls) <= {"ARM", "FRTR"}
    assert all(is_allowed(c) or is_control_allowed(c) for c in scope.sent)


def test_status_reports_the_users_trigger_mode(bench, qtbot):
    worker, scope, rec = bench(mode="NORM")
    worker.set_synchronized(True)
    start = len(rec.statuses)
    qtbot.waitUntil(lambda: len(rec.waveforms) >= 3, timeout=3000)
    modes = {s.acquisition.trigger_mode for s in rec.statuses[start:]}
    assert modes == {TriggerMode.NORM}  # never the app's own Single/Stopped (FR-010)


def test_arms_while_the_gui_draws_but_reads_only_after_it_consumed(bench, qtbot):
    worker, scope, rec = bench(consume=False)
    worker.set_synchronized(True)
    qtbot.waitUntil(lambda: len(rec.waveforms) == 1, timeout=3000)
    qtbot.wait(150)
    assert len(rec.waveforms) == 1  # the GUI has not consumed the first set
    assert scope.controls.count("ARM") == 2  # but the next acquisition is already armed
    reads = len([c for c in scope.sent if c.endswith("WF? ALL")])
    qtbot.wait(100)
    assert len([c for c in scope.sent if c.endswith("WF? ALL")]) == reads
    worker.waveforms_consumed()
    qtbot.waitUntil(lambda: len(rec.waveforms) == 2, timeout=3000)


def test_one_channel_transfer_per_cycle(bench, qtbot, monkeypatch):
    worker, scope, rec = bench()
    cycles = []
    step = worker._sync_step

    def counting_step():
        before = sum(c.endswith("WF? ALL") for c in scope.sent)
        delay = step()
        cycles.append(sum(c.endswith("WF? ALL") for c in scope.sent) - before)
        return delay

    monkeypatch.setattr(worker, "_sync_step", counting_step)
    worker.set_synchronized(True)
    qtbot.waitUntil(lambda: len(rec.waveforms) >= 3, timeout=3000)
    assert max(cycles) == 1


def test_pause_arms_nothing(bench, qtbot):
    worker, scope, rec = bench()
    worker.set_synchronized(True)
    qtbot.waitUntil(lambda: len(rec.waveforms) >= 2, timeout=3000)
    worker.set_capture_paused(True)
    qtbot.wait(100)  # an acquisition armed before the pause may still complete
    arms = scope.controls.count("ARM")
    qtbot.wait(300)
    assert scope.controls.count("ARM") == arms
    assert scope.trigger_mode == "STOP"
    worker.set_capture_paused(False)
    qtbot.waitUntil(lambda: scope.controls.count("ARM") > arms, timeout=2000)


def test_auto_forces_one_trigger_after_half_a_second(bench, qtbot):
    worker, scope, rec = bench(triggers=False)
    writes = timed_writes(scope)
    worker.set_synchronized(True)
    qtbot.waitUntil(lambda: scope.controls.count("FRTR") >= 2, timeout=4000)
    arms = [t for t, c in writes if c == "ARM"]
    forces = [t for t, c in writes if c == "FRTR"]
    assert forces[0] - arms[0] >= worker_module.FORCE_AFTER_S
    assert forces[1] > arms[1]  # one force per arm
    qtbot.waitUntil(lambda: bool(rec.waveforms), timeout=2000)
    assert len({w.trigger_time for w in rec.waveforms[-1].values()}) == 1


@pytest.mark.parametrize("mode", ["NORM", "STOP"])
def test_normal_and_stopped_wait_for_real_triggers(bench, qtbot, mode):
    worker, scope, rec = bench(mode=mode, triggers=False)
    worker.set_synchronized(True)
    qtbot.waitUntil(
        lambda: bool(rec.statuses) and rec.statuses[-1].acq_state is AcqState.WAITING_FOR_TRIGGER,
        timeout=3000,
    )
    assert "FRTR" not in scope.controls
    assert rec.statuses[-1].acquisition.trigger_mode is TriggerMode[mode]


@pytest.mark.parametrize("mode", ["AUTO", "NORM", "SINGLE", "STOP"])
def test_switching_off_restores_the_trigger_mode(bench, qtbot, caplog, mode):
    worker, scope, rec = bench(mode=mode)
    with caplog.at_level(logging.INFO):
        worker.set_synchronized(True)
        qtbot.waitUntil(lambda: scope.controls.count("ARM") >= 3, timeout=3000)
        worker.set_synchronized(False)
    assert scope.controls[-1] == f"TRMD {mode}"
    assert scope.trigger_mode in ({mode, "STOP"} if mode == "SINGLE" else {mode})
    assert rec.syncs == [(True, ""), (False, "")]
    on = f"synchronized capture on (was {TriggerMode[mode].value})"
    assert on in caplog.messages
    off = [m for m in caplog.messages if m.startswith("synchronized capture off (switched off)")]
    assert off and off[0].endswith("triggers forced")
    assert set(scope.controls) <= {"ARM", "FRTR", f"TRMD {mode}"}


def test_switching_off_while_waiting_restores_at_once(bench, qtbot):
    worker, scope, rec = bench(mode="NORM", triggers=False)
    worker.set_synchronized(True)
    qtbot.wait(300)
    assert scope.trigger_mode == "SINGLE"  # armed, nothing triggers
    start = time.monotonic()
    worker.set_synchronized(False)
    assert time.monotonic() - start < 2.0
    assert scope.trigger_mode == "NORM"


def test_disconnect_restores(bench, qtbot):
    worker, scope, rec = bench()
    worker.set_synchronized(True)
    qtbot.waitUntil(lambda: len(rec.waveforms) >= 2, timeout=3000)
    worker.close_connection()
    assert scope.controls[-1] == "TRMD AUTO" and scope.trigger_mode == "AUTO"
    assert rec.states[-1][0] is ConnectionState.DISCONNECTED


def test_external_change_while_armed_ends_without_restoring(bench, qtbot):
    worker, scope, rec = bench(mode="NORM", triggers=False)
    worker.set_synchronized(True)
    qtbot.wait(100)
    scope._set_mode("AUTO")  # someone pressed Auto on the front panel
    qtbot.waitUntil(lambda: rec.syncs[-1] == (False, EXTERNAL), timeout=2000)
    assert not any(c.startswith("TRMD") for c in scope.controls)
    assert scope.trigger_mode == "AUTO"
    assert rec.syncs.count((False, EXTERNAL)) == 1 and len(rec.syncs) == 2


def test_external_change_between_updates_is_caught_before_arming(bench, qtbot):
    worker, scope, rec = bench()
    worker.set_synchronized(True)
    qtbot.waitUntil(lambda: len(rec.waveforms) >= 2, timeout=3000)
    worker.set_capture_paused(True)
    qtbot.waitUntil(lambda: worker._sync.phase is worker_module.SyncPhase.IDLE, timeout=2000)
    qtbot.waitUntil(lambda: scope.trigger_mode == "STOP", timeout=2000)
    arms = scope.controls.count("ARM")
    scope._set_mode("NORM")
    worker.set_capture_paused(False)
    qtbot.waitUntil(lambda: rec.syncs[-1] == (False, EXTERNAL), timeout=2000)
    assert scope.controls.count("ARM") == arms  # the user's Normal was not overwritten
    assert scope.trigger_mode == "NORM"


def test_link_lost_tells_what_to_set_back(bench, qtbot):
    worker, scope, rec = bench()
    worker.set_synchronized(True)
    qtbot.waitUntil(lambda: len(rec.waveforms) >= 2, timeout=3000)
    scope.reset = True  # cable unplugged
    qtbot.waitUntil(lambda: rec.states[-1][0] is ConnectionState.LOST, timeout=10000)
    message = rec.states[-1][1]
    assert message.endswith("The scope may be left stopped - set its trigger mode back to Auto.")
    assert rec.syncs[-1] == (False, "")


def test_conflict_tells_what_to_set_back(bench, qtbot):
    worker, scope, rec = bench(mode="NORM")
    worker.set_synchronized(True)
    qtbot.waitUntil(lambda: len(rec.waveforms) >= 2, timeout=3000)
    query = scope.query
    scope.query = lambda command: "C1:VDIV 1 V" if command == "TRMD?" else query(command)
    qtbot.waitUntil(lambda: rec.states[-1][0] is ConnectionState.LOST, timeout=5000)
    message = rec.states[-1][1]
    assert message.startswith(worker_module.CONFLICT_MESSAGE)
    assert message.endswith("set its trigger mode back to Normal.")


def test_failed_restore_names_the_mode(bench, qtbot):
    worker, scope, rec = bench(mode="NORM")
    worker.set_synchronized(True)
    qtbot.waitUntil(lambda: len(rec.waveforms) >= 1, timeout=3000)
    query = scope.query
    scope.query = lambda command: "TRMD AUTO" if command == "TRMD?" else query(command)
    worker.set_synchronized(False)
    assert rec.syncs[-1] == (
        False,
        "Could not restore the trigger mode - set the scope back to Normal",
    )
