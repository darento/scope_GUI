"""Worker that owns the scope connection; lives in its own QThread (Constitution Principle II).

The GUI talks to it only through queued signals/slots, except ``abort()``, which is thread-safe
and used to cancel a pending connect or to break a blocked read on shutdown (research R8).
"""

import logging
import threading
import time
from collections import deque
from dataclasses import replace

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from .driver import ScopeDriver
from .errors import ScopeBusy, ScopeError, ScopeProtocolError, ScopeTimeout, ScopeUnreachable
from .models import AcqState, ConnectionState, InstrumentIdentity, InstrumentSupport, TriggerMode
from .settings import to_visa_resource

log = logging.getLogger(__name__)

IDLE_INTERVAL_MS = 200  # between cycles when nothing new was transferred
WAIT_FOR_TRIGGER_S = 1.0  # NORM/SINGLE with no new trigger for this long -> waiting (R5)
LOST_AFTER_S = 5.0  # unrecovered failures for this long -> connection lost (FR-007)
RATE_WINDOW = 6  # acquisitions used for the update-rate average
RATE_STALE_S = 2.0  # no acquisition for this long -> rate shows 0


def user_message(exc: Exception) -> str:
    """English, user-facing text for a connection failure."""
    if isinstance(exc, ScopeUnreachable):
        return str(exc)
    if isinstance(exc, ScopeBusy):
        return "Instrument busy (used by another client) - try again"
    if isinstance(exc, ScopeTimeout):
        return "Instrument did not respond (timeout)"
    if isinstance(exc, ValueError):
        return str(exc)
    return f"Connection failed: {exc}"


class AcquisitionWorker(QObject):
    state_changed = Signal(object, str)  # ConnectionState, message
    identity_received = Signal(object)  # InstrumentIdentity
    confirmation_needed = Signal(object)  # InstrumentIdentity not SUPPORTED
    status_updated = Signal(object)  # ScopeStatus
    waveforms_updated = Signal(object)  # dict[str, Waveform]
    rate_updated = Signal(float)  # new acquisitions per second

    def __init__(self, driver_factory=ScopeDriver):
        super().__init__()
        self._driver_factory = driver_factory
        self._driver: ScopeDriver | None = None
        self._state = ConnectionState.DISCONNECTED
        self._cancelled = threading.Event()
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
                self._set_state(ConnectionState.ERROR, user_message(exc))
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

    @Slot()
    def close_connection(self) -> None:
        self._stop_live()
        self._pending_identity = None
        self._drop_driver()
        self._set_state(ConnectionState.DISCONNECTED)

    @Slot()
    def shutdown(self) -> None:
        self._stop_live()
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
        cycle_start = time.monotonic()
        try:
            transferred = self._poll()
        except ScopeProtocolError as exc:
            log.warning("skipping malformed data: %s", exc)
            transferred = False
        except Exception as exc:
            if self._cancelled.is_set():
                return  # shutting down; the session was closed under us
            self._handle_failure(exc, cycle_start)
            return
        self._failure_since = None
        self._timer.start(0 if transferred else IDLE_INTERVAL_MS)

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
            self.waveforms_updated.emit(waveforms)
        self.rate_updated.emit(self._rate(now))
        return bool(waveforms)

    def _rate(self, now: float) -> float:
        times = self._acq_times
        if len(times) < 2 or now - times[-1] > RATE_STALE_S:
            return 0.0
        return (len(times) - 1) / (times[-1] - times[0])

    def _handle_failure(self, exc: Exception, cycle_start: float) -> None:
        if self._failure_since is None:
            self._failure_since = cycle_start
        failing_for = time.monotonic() - self._failure_since
        log.warning("I/O failure after %.1f s: %s", failing_for, exc)
        # A busy scope is retried; anything else gets one device-clear + *IDN? check (R4).
        healthy = not isinstance(exc, ScopeBusy) and self._driver.recover()
        if (healthy or isinstance(exc, ScopeBusy)) and (
            time.monotonic() - self._failure_since < LOST_AFTER_S
        ):
            self._timer.start(IDLE_INTERVAL_MS)
            return
        self._drop_driver()
        self._set_state(ConnectionState.LOST, f"Connection lost ({user_message(exc)})")
