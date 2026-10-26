"""Main window: wires the worker thread to the widgets (contracts/ui.md)."""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDockWidget, QLabel, QMainWindow, QMessageBox, QSplitter

from ..driver import ScopeDriver
from ..models import ConnectionState, InstrumentIdentity, ScopeStatus, Waveform
from ..settings import log_dir, save_last_address
from ..worker import AcquisitionWorker
from .connection_bar import ConnectionBar
from .measurements_panel import MeasurementsPanel
from .scope_plot import ScopePlot
from .side_panel import SidePanel

log = logging.getLogger(__name__)

SHUTDOWN_GRACE_MS = 1000


@dataclass
class LiveViewState:
    """GUI-only view state; never sent to the scope (data-model.md)."""

    paused: bool = False
    hidden_channels: set[str] = field(default_factory=set)
    update_rate_hz: float = 0.0
    stale: bool = False
    last_update: datetime | None = None


class MainWindow(QMainWindow):
    request_connect = Signal(str)
    request_confirm = Signal(bool)
    request_disconnect = Signal()
    request_shutdown = Signal()

    def __init__(self, address: str = "", driver_factory=ScopeDriver):
        super().__init__()
        self.setWindowTitle("Scope GUI")
        self.resize(1400, 900)
        self._pending_address = ""
        self._state = ConnectionState.DISCONNECTED
        self.view = LiveViewState()
        self._last_settings = None  # channel and acquisition settings of the last status

        self.connection_bar = ConnectionBar(address)
        toolbar = self.addToolBar("Connection")
        toolbar.setMovable(False)
        toolbar.addWidget(self.connection_bar)

        self.scope_plot = ScopePlot()
        self.side_panel = SidePanel()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.scope_plot)
        splitter.addWidget(self.side_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setCollapsible(0, False)
        self.setCentralWidget(splitter)

        # Analysis docks (specs/002-waveform-analysis/contracts/ui.md).
        self.measurements_panel = MeasurementsPanel()
        self.measurements_dock = self._add_dock("Measurements", self.measurements_panel)
        self._build_menu()

        self.rate_label = QLabel()
        self.statusBar().addPermanentWidget(self.rate_label)
        self._update_rate_label()

        self.side_panel.hidden_changed.connect(self._on_hidden_changed)
        self.side_panel.paused_changed.connect(self._on_paused_changed)

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
        self.worker.status_updated.connect(self._on_status)
        self.worker.waveforms_updated.connect(self._on_waveforms)
        self.worker.rate_updated.connect(self._on_rate)

        self.connection_bar.connect_requested.connect(self._on_connect_requested)
        self.connection_bar.disconnect_requested.connect(self._on_disconnect_requested)

        self.worker_thread.start()

    def _add_dock(self, title: str, widget) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(title)
        dock.setWidget(widget)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        return dock

    def _build_menu(self) -> None:
        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.measurements_dock.toggleViewAction())
        self.view_menu = view_menu
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

    def _on_hidden_changed(self, hidden: set[str]) -> None:
        self.view.hidden_channels = set(hidden)
        self.scope_plot.set_hidden(self.view.hidden_channels)

    def _on_paused_changed(self, paused: bool) -> None:
        # Pausing freezes only the PC display; the worker and the scope keep running (FR-016).
        self.view.paused = paused
        self._update_rate_label()

    # --- worker signals ---------------------------------------------------------------------
    def _on_state_changed(self, state: ConnectionState, message: str) -> None:
        self._state = state
        self.connection_bar.set_state(state, message)
        if state is ConnectionState.CONNECTED:
            save_last_address(self._pending_address)
            self._set_stale(False)
        elif state in (ConnectionState.LOST, ConnectionState.ERROR):
            self._set_stale(True)
            self.side_panel.set_not_live()
            self.view.update_rate_hz = 0.0
        elif state is ConnectionState.DISCONNECTED:
            self._set_stale(False)
            self.scope_plot.clear()
            self.side_panel.clear()
            self.view.update_rate_hz = 0.0
            self.view.last_update = None
        self._update_rate_label()
        if message and state in (ConnectionState.ERROR, ConnectionState.LOST):
            self.statusBar().showMessage(message)

    def _on_status(self, status: ScopeStatus) -> None:
        self.side_panel.set_status(status)
        # FR-022: statistics are kept, but warn that they mix settings (research R14).
        current = (status.channels, status.acquisition)
        if self._last_settings is not None and current != self._last_settings:
            self.measurements_panel.set_settings_changed()
        self._last_settings = current
        if not self.view.paused:
            self.scope_plot.set_status(status)

    def _on_waveforms(self, waveforms: dict[str, Waveform]) -> None:
        if self.view.paused:
            return
        self.scope_plot.set_waveforms(waveforms)
        # Every received channel is measured, also those hidden on the PC (FR-008).
        self.measurements_panel.process(waveforms)
        self.view.last_update = datetime.now()
        self._update_rate_label()

    def _on_rate(self, rate: float) -> None:
        self.view.update_rate_hz = rate
        self._update_rate_label()

    def _set_stale(self, stale: bool) -> None:
        self.view.stale = stale
        self.scope_plot.set_stale(stale)

    def _update_rate_label(self) -> None:
        last = self.view.last_update.strftime("%H:%M:%S") if self.view.last_update else "—"
        text = f"{self.view.update_rate_hz:.1f} updates/s · last update {last}"
        if self.view.paused:
            text = f"PAUSED · {text}"
        self.rate_label.setText(text)

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
