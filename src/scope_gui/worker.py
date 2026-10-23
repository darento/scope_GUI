"""Worker that owns the scope connection; lives in its own QThread (Constitution Principle II).

The GUI talks to it only through queued signals/slots, except ``abort()``, which is thread-safe
and used to cancel a pending connect or to break a blocked read on shutdown (research R8).
"""

import logging
import threading

from PySide6.QtCore import QObject, QThread, Signal, Slot

from .driver import ScopeDriver
from .errors import ScopeBusy, ScopeError, ScopeTimeout, ScopeUnreachable
from .models import ConnectionState, InstrumentIdentity, InstrumentSupport
from .settings import to_visa_resource

log = logging.getLogger(__name__)


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

    def __init__(self, driver_factory=ScopeDriver):
        super().__init__()
        self._driver_factory = driver_factory
        self._driver: ScopeDriver | None = None
        self._state = ConnectionState.DISCONNECTED
        self._cancelled = threading.Event()
        self._pending_identity: InstrumentIdentity | None = None

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
        """Start the live acquisition loop (User Story 2)."""

    def _stop_live(self) -> None:
        """Stop the live acquisition loop (User Story 2)."""
