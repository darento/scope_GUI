"""Main window: wires the worker thread to the widgets (contracts/ui.md)."""

import logging

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QMainWindow, QMessageBox

from ..driver import ScopeDriver
from ..models import ConnectionState, InstrumentIdentity
from ..settings import log_dir, save_last_address
from ..worker import AcquisitionWorker
from .connection_bar import ConnectionBar

log = logging.getLogger(__name__)

SHUTDOWN_GRACE_MS = 1000


class MainWindow(QMainWindow):
    request_connect = Signal(str)
    request_confirm = Signal(bool)
    request_disconnect = Signal()
    request_shutdown = Signal()

    def __init__(self, address: str = "", driver_factory=ScopeDriver):
        super().__init__()
        self.setWindowTitle("Scope GUI")
        self.resize(1200, 700)
        self._pending_address = ""
        self._state = ConnectionState.DISCONNECTED

        self.connection_bar = ConnectionBar(address)
        self.setMenuWidget(None)
        self._build_menu()
        toolbar = self.addToolBar("Connection")
        toolbar.setMovable(False)
        toolbar.addWidget(self.connection_bar)
        self.setCentralWidget(QLabel("Connect to the scope to see its waveforms."))

        self.worker_thread = QThread(self)
        self.worker_thread.setObjectName("scope-io")
        self.worker = AcquisitionWorker(driver_factory)
        self.worker.moveToThread(self.worker_thread)

        self.request_connect.connect(self.worker.connect_to)
        self.request_confirm.connect(self.worker.confirm_unsupported)
        self.request_disconnect.connect(self.worker.close_connection)
        self.request_shutdown.connect(self.worker.shutdown)
        self.worker.state_changed.connect(self._on_state_changed)
        self.worker.identity_received.connect(self.connection_bar.set_identity)
        self.worker.confirmation_needed.connect(self._on_confirmation_needed)

        self.connection_bar.connect_requested.connect(self._on_connect_requested)
        self.connection_bar.disconnect_requested.connect(self._on_disconnect_requested)

        self.worker_thread.start()

    def _build_menu(self) -> None:
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("Open log folder", self.open_log_folder)

    # --- user actions -----------------------------------------------------------------------
    def _on_connect_requested(self, address: str) -> None:
        self._pending_address = address
        self.statusBar().clearMessage()
        self.request_connect.emit(address)

    def _on_disconnect_requested(self) -> None:
        if self._state is ConnectionState.CONNECTING:
            self.worker.abort()  # break a pending connect; the worker then reports DISCONNECTED
        self.request_disconnect.emit()

    def open_log_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir())))

    # --- worker signals ---------------------------------------------------------------------
    def _on_state_changed(self, state: ConnectionState, message: str) -> None:
        self._state = state
        self.connection_bar.set_state(state, message)
        if state is ConnectionState.CONNECTED:
            save_last_address(self._pending_address)
        if message and state in (ConnectionState.ERROR, ConnectionState.LOST):
            self.statusBar().showMessage(message)

    def _on_confirmation_needed(self, identity: InstrumentIdentity) -> None:
        self.request_confirm.emit(self.ask_continue(identity))

    def ask_continue(self, identity: InstrumentIdentity) -> bool:
        answer = QMessageBox.warning(
            self,
            "Unsupported instrument",
            f"The instrument reports {identity.manufacturer} {identity.model} "
            f"(firmware {identity.firmware}), which is {identity.support.value}.\n\n"
            "This application was built and tested for the LeCroy WR610Zi. "
            "Continue at your own risk?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    # --- shutdown (research R8) -------------------------------------------------------------
    def closeEvent(self, event) -> None:
        self.request_shutdown.emit()
        if not self.worker_thread.wait(SHUTDOWN_GRACE_MS):
            log.info("worker busy on close; aborting pending I/O")
            self.worker.abort()
            self.worker_thread.wait(5000)
        super().closeEvent(event)
