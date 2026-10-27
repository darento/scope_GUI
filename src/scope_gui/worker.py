"""Worker that owns the scope connection; lives in its own QThread (Constitution Principle II).

The GUI talks to it only through queued signals/slots, except ``abort()``, which is thread-safe
and used to cancel a pending connect or to break a blocked read on shutdown (research R8),
``waveforms_consumed()``, which lets the next waveforms go out (at most one set queued), and
``set_capture_paused()``.

Synchronized capture (feature 003, constitution III "Acquisition control"): while the user has it
on, the worker arms one acquisition at a time, so every set it emits has all channels of one
trigger, and restores the scope's trigger mode when it ends.
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace
from enum import Enum

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from .driver import ScopeDriver
from .errors import (
    ScopeBusy,
    ScopeError,
    ScopeLost,
    ScopeProtocolError,
    ScopeReplyMismatch,
    ScopeTimeout,
    ScopeUnreachable,
)
from .models import (
    AcqState,
    ConnectionState,
    InstrumentIdentity,
    InstrumentSupport,
    ScopeStatus,
    TriggerMode,
    Waveform,
)
from .settings import to_visa_resource

log = logging.getLogger(__name__)

IDLE_INTERVAL_MS = 200  # between cycles when nothing new was transferred
BUSY_GUI_INTERVAL_MS = 5  # re-check while the GUI is still handling the last waveforms
WAIT_FOR_TRIGGER_S = 1.0  # NORM/SINGLE with no new trigger for this long -> waiting (R5)
LOST_AFTER_S = 5.0  # unrecovered failures for this long -> connection lost (FR-007)
RATE_WINDOW = 6  # acquisitions used for the update-rate average
RATE_STALE_S = 2.0  # no acquisition for this long -> rate shows 0
CONFLICT_AFTER = 3  # consecutive cycles with foreign replies -> another program (FR-021)
CONFLICT_MESSAGE = "Another program is using the scope - reconnect when it has finished"
SYNC_POLL_MS = 10  # TRMD? polling while an armed acquisition completes (003 research R3)
FORCE_AFTER_S = 0.5  # Auto: force a trigger when none arrived this long after arming (R4)
EXTERNAL_CHANGE_MESSAGE = "Trigger mode changed on the scope - synchronized capture switched off"
LEFT_STOPPED = "The scope may be left stopped - set its trigger mode back to {mode}."


def user_message(exc: Exception) -> str:
    """English, user-facing text for a connection failure."""
    if isinstance(exc, (ScopeUnreachable, ValueError)):
        return str(exc)
    if isinstance(exc, ScopeBusy):
        return "Instrument busy (used by another client) - try again"
    if isinstance(exc, ScopeTimeout):
        return "Instrument did not respond (timeout)"
    if isinstance(exc, ScopeLost):
        return "Network link to the scope was interrupted"
    if isinstance(exc, ScopeReplyMismatch):
        return CONFLICT_MESSAGE
    # Anything else: keep the UI short and English; the details are in the log.
    return "Communication error (see log for details)"


class SyncPhase(Enum):
    IDLE = "idle"  # the next cycle arms (unless paused)
    ARMED = "armed"  # polling TRMD? until the acquisition is done
    READING = "reading"  # one channel per cycle (R8)


@dataclass
class SyncCapture:
    """One synchronized capture session (data-model.md)."""

    restore_mode: TriggerMode
    phase: SyncPhase = SyncPhase.IDLE
    armed_at: float = 0.0
    forced: bool = False
    waiting_shown: bool = False
    armed_count: int = 0
    forced_count: int = 0
    status: ScopeStatus | None = None
    pending: dict[str, Waveform] = field(default_factory=dict)


class AcquisitionWorker(QObject):
    state_changed = Signal(object, str)  # ConnectionState, message
    identity_received = Signal(object)  # InstrumentIdentity
    confirmation_needed = Signal(object)  # InstrumentIdentity not SUPPORTED
    status_updated = Signal(object)  # ScopeStatus
    waveforms_updated = Signal(object)  # dict[str, Waveform]
    rate_updated = Signal(float)  # new acquisitions per second
    sync_changed = Signal(bool, str)  # synchronized capture on, user message ("" when as asked)

    def __init__(self, driver_factory=ScopeDriver):
        super().__init__()
        self._driver_factory = driver_factory
        self._driver: ScopeDriver | None = None
        self._state = ConnectionState.DISCONNECTED
        self._cancelled = threading.Event()
        # Set while the GUI has no waveforms waiting: a slow GUI then lowers the rate instead
        # of queueing acquisitions without end and stopping responding (Principle II).
        self._consumed = threading.Event()
        self._capture_paused = threading.Event()  # synchronized capture arms nothing while set
        self._sync: SyncCapture | None = None  # None: synchronized capture off
        self._pending_identity: InstrumentIdentity | None = None
        # Child of self, so it moves to the worker thread together with the worker.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._cycle)
        self._reset_live()

    def _reset_live(self) -> None:
        self._last_trigger: float | None = None
        self._last_enabled: tuple[str, ...] | None = None
        self._last_new_at = time.monotonic()
        self._acq_times: deque[float] = deque(maxlen=RATE_WINDOW)
        self._failure_since: float | None = None
        self._conflicts = 0  # consecutive cycles that got another query's reply
        self._consumed.set()

    def waveforms_consumed(self) -> None:
        """The GUI has handled the last waveforms. Callable from any thread."""
        self._consumed.set()

    def set_capture_paused(self, paused: bool) -> None:
        """The display is paused: arm no new acquisition (FR-011). Callable from any thread."""
        if paused:
            self._capture_paused.set()
        else:
            self._capture_paused.clear()

    @property
    def state(self) -> ConnectionState:
        return self._state

    def _set_state(self, state: ConnectionState, message: str = "") -> None:
        self._state = state
        log.info("state %s %s", state.value, message)
        self.state_changed.emit(state, message)

    # --- slots (run in the worker thread) ---------------------------------------------------
    @Slot(str)
    def connect_to(self, address: str) -> None:
        if self._state in (ConnectionState.CONNECTING, ConnectionState.CONNECTED):
            return
        self._cancelled.clear()
        self._set_state(ConnectionState.CONNECTING, address)
        try:
            resource = to_visa_resource(address)
            self._driver = self._driver_factory()
            identity = self._driver.connect(resource)
        except (ScopeError, ValueError) as exc:
            self._drop_driver()
            if self._cancelled.is_set():
                self._set_state(ConnectionState.DISCONNECTED)
            else:
                log.warning("connect failed: %s", exc)
                message = user_message(exc)
                if isinstance(exc, ScopeTimeout):  # port open but reply lost: likely shared (R13)
                    message += " - another program may be using the scope"
                self._set_state(ConnectionState.ERROR, message)
            return
        if self._cancelled.is_set():
            self._drop_driver()
            self._set_state(ConnectionState.DISCONNECTED)
            return
        self.identity_received.emit(identity)
        if identity.support is InstrumentSupport.SUPPORTED:
            self._on_connected()
        else:
            self._pending_identity = identity
            self.confirmation_needed.emit(identity)

    @Slot(bool)
    def confirm_unsupported(self, accept: bool) -> None:
        if self._pending_identity is None or self._state is not ConnectionState.CONNECTING:
            return
        identity, self._pending_identity = self._pending_identity, None
        if accept:
            log.warning("user accepted unsupported instrument %s", identity)
            self._on_connected()
        else:
            self._drop_driver()
            self._set_state(ConnectionState.DISCONNECTED)

    @Slot(bool)
    def set_synchronized(self, on: bool) -> None:
        if not on:
            self._end_sync("switched off")
            return
        if self._sync is not None or self._state is not ConnectionState.CONNECTED:
            return
        try:
            mode = self._driver.read_trigger_mode()
        except ScopeError as exc:
            log.warning("synchronized capture not started: %s", exc)
            self.sync_changed.emit(False, "Could not read the trigger mode - try again")
            return
        self._sync = SyncCapture(mode)
        log.info("synchronized capture on (was %s)", mode.value)
        self.sync_changed.emit(True, "")
        self._timer.start(0)

    @Slot()
    def close_connection(self) -> None:
        self._stop_live()
        self._end_sync("disconnect")
        self._pending_identity = None
        self._drop_driver()
        self._set_state(ConnectionState.DISCONNECTED)

    @Slot()
    def shutdown(self) -> None:
        self._stop_live()
        self._end_sync("close")
        self._drop_driver()
        QThread.currentThread().quit()

    # --- thread-safe ------------------------------------------------------------------------
    def abort(self) -> None:
        """Cancel a pending connect / break a blocked read. Callable from any thread."""
        self._cancelled.set()
        driver = self._driver
        if driver is not None:
            driver.close()

    # --- internals --------------------------------------------------------------------------
    def _drop_driver(self) -> None:
        driver, self._driver = self._driver, None
        if driver is not None:
            driver.close()

    def _on_connected(self) -> None:
        self._set_state(ConnectionState.CONNECTED)
        self._start_live()

    def _start_live(self) -> None:
        self._reset_live()
        self._timer.start(0)

    def _stop_live(self) -> None:
        self._timer.stop()

    # --- live loop (research R5, R8) --------------------------------------------------------
    @Slot()
    def _cycle(self) -> None:
        if self._state is not ConnectionState.CONNECTED or self._driver is None:
            return
        if self._sync is None and not self._consumed.is_set():
            self._timer.start(BUSY_GUI_INTERVAL_MS)
            return
        cycle_start = time.monotonic()
        try:
            if self._sync is not None:
                delay = self._sync_step()
            else:
                delay = 0 if self._poll() else IDLE_INTERVAL_MS
        except ScopeReplyMismatch as exc:
            # Never shown (the driver refused it); step back if it keeps happening (FR-021).
            self._conflicts += 1
            log.warning("cycle discarded (%d/%d): %s", self._conflicts, CONFLICT_AFTER, exc)
            if self._conflicts >= CONFLICT_AFTER:
                self._lose(CONFLICT_MESSAGE)
                return
            self._restart_sync()
            self._timer.start(IDLE_INTERVAL_MS)
            return
        except ScopeProtocolError as exc:
            log.warning("skipping malformed data: %s", exc)
            self._restart_sync()
            delay = IDLE_INTERVAL_MS
        except Exception as exc:
            if self._cancelled.is_set():
                return  # shutting down; the session was closed under us
            self._handle_failure(exc, cycle_start)
            return
        self._failure_since = None
        self._conflicts = 0
        if delay is not None:
            self._timer.start(delay)

    def _poll(self) -> bool:
        """One cycle: settings, novelty check, transfers. Returns True if waveforms were read."""
        driver = self._driver
        status = driver.read_status()
        enabled = status.enabled_channels
        now = time.monotonic()
        waveforms = {}
        if enabled:
            desc = driver.read_descriptor(enabled[0])
            if desc.trigger_time != self._last_trigger or enabled != self._last_enabled:
                waveforms = {ch: driver.read_waveform(ch) for ch in enabled}
                self._last_trigger = waveforms[enabled[0]].trigger_time
                self._last_enabled = enabled
                self._last_new_at = now
                self._acq_times.append(now)
        mode = status.acquisition.trigger_mode
        if mode is TriggerMode.STOP:
            acq_state = AcqState.STOPPED
        elif mode in (TriggerMode.NORM, TriggerMode.SINGLE) and (
            now - self._last_new_at > WAIT_FOR_TRIGGER_S
        ):
            acq_state = AcqState.WAITING_FOR_TRIGGER
        else:
            acq_state = AcqState.ACQUIRING
        self.status_updated.emit(replace(status, acq_state=acq_state))
        if waveforms:
            self._consumed.clear()
            self.waveforms_updated.emit(waveforms)
        self.rate_updated.emit(self._rate(now))
        return bool(waveforms)

    # --- synchronized capture (003 data-model.md) ----------------------------------------------
    def _sync_step(self) -> int | None:
        """One cycle of synchronized capture; the delay to the next cycle, None if it ended."""
        sync, driver = self._sync, self._driver
        if sync.phase is SyncPhase.IDLE:
            if self._capture_paused.is_set():
                return IDLE_INTERVAL_MS
            # The scope stopped after the last acquisition; Auto/Normal now means someone else
            # changed it between two updates (R6). The first arm starts from the user's mode.
            if sync.armed_count and not self._sync_mode_ok(driver.read_trigger_mode()):
                return None
            driver.arm()
            sync.armed_count += 1
            sync.armed_at = time.monotonic()
            sync.forced = sync.waiting_shown = False
            sync.phase = SyncPhase.ARMED
            # Read while the scope acquires; its TRMD? is the first poll (R3).
            sync.status = driver.read_status()
            return self._sync_poll(sync.status.acquisition.trigger_mode)
        if sync.phase is SyncPhase.ARMED:
            return self._sync_poll(driver.read_trigger_mode())
        if not self._consumed.is_set():  # at most one set waiting for the GUI
            return BUSY_GUI_INTERVAL_MS
        channels = sync.status.enabled_channels
        missing = [ch for ch in channels if ch not in sync.pending]
        if missing:  # one transfer per cycle, so a switch-off waits for one at most (R8)
            sync.pending[missing[0]] = driver.read_waveform(missing[0])
            if len(missing) > 1:
                return 0
        waveforms, sync.pending = sync.pending, {}
        sync.phase = SyncPhase.IDLE
        if len({w.trigger_time for w in waveforms.values()}) > 1:
            log.warning("synchronized set with different trigger times")  # the scope was stopped
        now = time.monotonic()
        self._last_new_at = now
        self.status_updated.emit(self._sync_status(AcqState.ACQUIRING))
        if waveforms:
            self._acq_times.append(now)
            self._consumed.clear()
            self.waveforms_updated.emit(waveforms)
        self.rate_updated.emit(self._rate(now))
        return 0 if waveforms else IDLE_INTERVAL_MS

    def _sync_poll(self, mode: TriggerMode) -> int | None:
        sync = self._sync
        if not self._sync_mode_ok(mode):
            return None
        if mode is TriggerMode.STOP:  # done: all channels hold this one acquisition
            sync.phase = SyncPhase.READING
            return 0
        armed_for = time.monotonic() - sync.armed_at
        if sync.restore_mode is TriggerMode.AUTO and not sync.forced and armed_for >= FORCE_AFTER_S:
            self._driver.force_trigger()
            sync.forced = True
            sync.forced_count += 1
        if armed_for > WAIT_FOR_TRIGGER_S and not sync.waiting_shown:
            sync.waiting_shown = True
            self.status_updated.emit(self._sync_status(AcqState.WAITING_FOR_TRIGGER))
            self.rate_updated.emit(self._rate(time.monotonic()))
        return SYNC_POLL_MS

    def _sync_mode_ok(self, mode: TriggerMode) -> bool:
        """The app only ever leaves the scope in Single or Stopped (FR-008)."""
        if mode in (TriggerMode.SINGLE, TriggerMode.STOP):
            return True
        self._end_sync("trigger mode changed on the scope", restore=False)
        self.sync_changed.emit(False, EXTERNAL_CHANGE_MESSAGE)
        return False

    def _sync_status(self, acq_state: AcqState) -> ScopeStatus:
        """The status read while armed, with the user's trigger mode (no settings note, R7)."""
        status = self._sync.status
        acquisition = replace(status.acquisition, trigger_mode=self._sync.restore_mode)
        return replace(status, acquisition=acquisition, acq_state=acq_state)

    def _restart_sync(self) -> None:
        """After a failed cycle, arm again rather than continue a half-read set."""
        if self._sync is not None:
            self._sync.phase = SyncPhase.IDLE
            self._sync.pending = {}

    def _end_sync(self, reason: str, restore: bool = True) -> None:
        """End the session; restore the trigger mode unless someone else changed it or the link
        is gone (FR-004, FR-008, FR-009). Emits ``sync_changed(False, ...)``, except after an
        external change, whose caller emits its own message."""
        sync, self._sync = self._sync, None
        if sync is None:
            return
        self._last_trigger = None  # the normal loop transfers the next acquisition it sees
        message = ""
        if restore and self._driver is not None:
            try:
                self._driver.restore_trigger_mode(sync.restore_mode)
            except Exception as exc:
                log.warning("restoring the trigger mode failed: %r", exc)
                mode = sync.restore_mode.value
                message = f"Could not restore the trigger mode - set the scope back to {mode}"
        log.info(
            "synchronized capture off (%s): %d acquisitions armed, %d triggers forced",
            reason,
            sync.armed_count,
            sync.forced_count,
        )
        if restore or reason != "trigger mode changed on the scope":
            self.sync_changed.emit(False, message)

    def _lose(self, message: str) -> None:
        """Connection lost (or taken by another program): tell the user what to set back."""
        if self._sync is not None:
            mode = self._sync.restore_mode.value
            self._end_sync("link lost", restore=False)
            message = f"{message}. {LEFT_STOPPED.format(mode=mode)}"
        self._drop_driver()
        self._set_state(ConnectionState.LOST, message)

    def _rate(self, now: float) -> float:
        times = self._acq_times
        if len(times) < 2 or now - times[-1] > RATE_STALE_S:
            return 0.0
        return (len(times) - 1) / (times[-1] - times[0])

    def _handle_failure(self, exc: Exception, cycle_start: float) -> None:
        if self._failure_since is None:
            self._failure_since = cycle_start
        failing_for = time.monotonic() - self._failure_since
        log.warning(
            "I/O failure after %.1f s: %r",
            failing_for,
            exc,
            exc_info=not isinstance(exc, ScopeError),
        )
        # A busy scope is retried; anything else gets one device-clear + *IDN? check (R4).
        healthy = not isinstance(exc, ScopeBusy) and self._driver.recover()
        if (healthy or isinstance(exc, ScopeBusy)) and (
            time.monotonic() - self._failure_since < LOST_AFTER_S
        ):
            self._restart_sync()
            self._timer.start(IDLE_INTERVAL_MS)
            return
        # Foreign replies since the last clean cycle: the lost replies went to another program.
        self._lose(CONFLICT_MESSAGE if self._conflicts else user_message(exc))
