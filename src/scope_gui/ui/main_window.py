"""Main window: wires the worker thread to the widgets (contracts/ui.md)."""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDockWidget, QLabel, QMainWindow, QMessageBox, QSplitter

from ..driver import ScopeDriver
from ..models import ConnectionState, InstrumentIdentity, ScopeStatus, Waveform
from ..settings import log_dir, save_last_address
from ..worker import AcquisitionWorker
from .connection_bar import ConnectionBar
from .histogram_panel import HistogramPanel
from .measurements_panel import MeasurementsPanel
from .scope_plot import ScopePlot
from .side_panel import SidePanel

log = logging.getLogger(__name__)

SHUTDOWN_GRACE_MS = 1000
SYNC_SHUTDOWN_GRACE_MS = 3000  # the worker restores the trigger mode before closing (003 R8)
WARNING_STYLE = "color: #f0a020; font-weight: bold;"
SYNC_TEXT = "Driving the scope: synchronized capture"
MIXED_TEXT = "Channels from different triggers - switch Synchronized capture on"


@dataclass
class LiveViewState:
    """GUI-only view state; never sent to the scope (data-model.md)."""

    paused: bool = False
    synchronized: bool = False  # the worker drives the acquisition (003)
    hidden_channels: set[str] = field(default_factory=set)
    update_rate_hz: float = 0.0
    stale: bool = False
    last_update: datetime | None = None


class MainWindow(QMainWindow):
    request_connect = Signal(str)
    request_confirm = Signal(bool)
    request_disconnect = Signal()
    request_shutdown = Signal()
    request_synchronized = Signal(bool)

    def __init__(self, address: str = "", driver_factory=ScopeDriver):
        super().__init__()
        self.setWindowTitle("Scope GUI")
        self.resize(1400, 900)
        self._pending_address = ""
        self._state = ConnectionState.DISCONNECTED
        self.view = LiveViewState()
        # Shown and measured in the next turn, with whether all channels share one trigger.
        self._to_measure: tuple[dict[str, Waveform], bool] | None = None
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
        self.histogram_panel = HistogramPanel()
        self.histogram_dock = self._add_dock("Histogram", self.histogram_panel)
        self.splitDockWidget(self.measurements_dock, self.histogram_dock, Qt.Orientation.Horizontal)
        self._build_menu()

        # Amber notes of synchronized capture and of mixed-trigger updates (003 contracts/ui.md).
        self.sync_label = QLabel(SYNC_TEXT)
        self.mixed_label = QLabel(MIXED_TEXT)
        for label in (self.sync_label, self.mixed_label):
            label.setStyleSheet(WARNING_STYLE)
            label.hide()
            self.statusBar().addPermanentWidget(label)
        self.rate_label = QLabel()
        self.statusBar().addPermanentWidget(self.rate_label)
        self._update_rate_label()

        self.side_panel.hidden_changed.connect(self._on_hidden_changed)
        self.side_panel.paused_changed.connect(self._on_paused_changed)
        self.side_panel.synchronized_toggled.connect(self.request_synchronized)

        # Waveform inspection (FR-014 to FR-018).
        self.side_panel.cursors_toggled.connect(self._on_cursors_toggled)
        self.side_panel.persistence_changed.connect(self.scope_plot.set_persistence)
        self.side_panel.reset_view_requested.connect(self.scope_plot.reset_view)
        self.measurements_panel.gate_changed.connect(self._on_gate_changed)
        self.measurements_panel.selection_changed.connect(self._on_measurement_selected)
        self.measurements_panel.processed.connect(self._refresh_histogram)
        self.scope_plot.level_dragged.connect(self.measurements_panel.update_level)
        self.measurements_panel.export_finished.connect(
            lambda _ok, message: self.statusBar().showMessage(message)
        )
        self._on_measurement_selected()

        self.worker_thread = QThread(self)
        self.worker_thread.setObjectName("scope-io")
        self.worker = AcquisitionWorker(driver_factory)
        self.worker.moveToThread(self.worker_thread)

        self.request_connect.connect(self.worker.connect_to)
        self.request_confirm.connect(self.worker.confirm_unsupported)
        self.request_disconnect.connect(self.worker.close_connection)
        self.request_shutdown.connect(self.worker.shutdown)
        self.request_synchronized.connect(self.worker.set_synchronized)
        self.worker.sync_changed.connect(self._on_sync_changed)
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
        view_menu.addAction(self.histogram_dock.toggleViewAction())
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

    def _on_cursors_toggled(self, on: bool) -> None:
        self.scope_plot.set_cursors_visible(on)
        if not on:
            self.measurements_panel.set_gate_between_cursors(False)

    def _on_gate_changed(self, between_cursors: bool) -> None:
        if between_cursors:
            self.side_panel.cursors_checkbox.setChecked(True)
        self.scope_plot.set_gate_enabled(between_cursors)

    def _on_measurement_selected(self) -> None:
        self.scope_plot.set_level_lines(self.measurements_panel.selected_spec)
        self._refresh_histogram()

    def _refresh_histogram(self) -> None:
        panel = self.measurements_panel
        self.histogram_panel.show_measurements(
            panel.specs, panel.stats, panel.selected_row, panel.coherence_log
        )

    def _on_paused_changed(self, paused: bool) -> None:
        # Pausing freezes only the PC display; the worker and the scope keep running (FR-016).
        self.view.paused = paused
        self.worker.set_capture_paused(paused)  # synchronized capture arms nothing (003 FR-011)
        self._update_rate_label()

    def _on_sync_changed(self, on: bool, message: str) -> None:
        self.view.synchronized = on
        self.side_panel.set_synchronized(on)
        self.sync_label.setVisible(on)
        if on:
            self.mixed_label.hide()
        if message:
            self.statusBar().showMessage(message)

    # --- worker signals ---------------------------------------------------------------------
    def _on_state_changed(self, state: ConnectionState, message: str) -> None:
        self._state = state
        self.connection_bar.set_state(state, message)
        self.side_panel.set_connected(state is ConnectionState.CONNECTED)
        if state is not ConnectionState.CONNECTED:
            self.mixed_label.hide()
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
            self.worker.waveforms_consumed()
            return
        try:
            self.scope_plot.set_waveforms(waveforms)
            self.view.last_update = datetime.now()
            self._update_rate_label()
        except BaseException:
            self.worker.waveforms_consumed()
            raise
        # Channels read one after another from a running scope may come from different
        # triggers (003 FR-014); synchronized capture prevents it.
        coherent = len({w.trigger_time for w in waveforms.values()}) <= 1
        self.mixed_label.setVisible(not coherent and not self.view.synchronized)
        # Measured in the next event-loop turn: input is handled between drawing and analysis,
        # so neither stalls the window for long at 2.5M points (FR-021). The worker sends the
        # next acquisition only after that, so every one shown is measured exactly once.
        self._to_measure = (waveforms, coherent)
        QTimer.singleShot(0, self._measure_shown)

    def _measure_shown(self) -> None:
        shown, self._to_measure = self._to_measure, None
        try:
            if shown is not None:
                # Every received channel is measured, also those hidden on the PC (FR-008).
                waveforms, coherent = shown
                self.measurements_panel.process(waveforms, self.scope_plot.gate(), coherent)
        finally:
            self.worker.waveforms_consumed()

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
        grace = SYNC_SHUTDOWN_GRACE_MS if self.view.synchronized else SHUTDOWN_GRACE_MS
        if not self.worker_thread.wait(grace):
            log.info("worker busy on close; aborting pending I/O")
            self.worker.abort()
            self.worker_thread.wait(5000)
        super().closeEvent(event)
