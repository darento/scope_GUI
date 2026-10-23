"""Address entry, connect/disconnect button, status indicator and identity (contracts/ui.md)."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from ..models import ConnectionState, InstrumentIdentity

STATE_COLORS = {
    ConnectionState.DISCONNECTED: "#8a8a8a",
    ConnectionState.CONNECTING: "#f0a020",
    ConnectionState.CONNECTED: "#30c030",
    ConnectionState.LOST: "#e03030",
    ConnectionState.ERROR: "#e03030",
}


class ConnectionBar(QWidget):
    connect_requested = Signal(str)
    disconnect_requested = Signal()

    def __init__(self, address: str = "", parent=None):
        super().__init__(parent)
        self.address_edit = QLineEdit(address)
        self.address_edit.setPlaceholderText("IP address, hostname or VISA resource")
        self.address_edit.setMinimumWidth(220)
        self.address_edit.returnPressed.connect(self._on_button)
        self.button = QPushButton("Connect")
        self.button.clicked.connect(self._on_button)
        self.status_dot = QLabel("●")
        self.status_text = QLabel()
        self.identity_label = QLabel()
        self.identity_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(QLabel("Address"))
        layout.addWidget(self.address_edit)
        layout.addWidget(self.button)
        layout.addSpacing(12)
        layout.addWidget(self.status_dot)
        layout.addWidget(self.status_text)
        layout.addSpacing(12)
        layout.addWidget(self.identity_label, 1)

        self._state = ConnectionState.DISCONNECTED
        self.set_state(ConnectionState.DISCONNECTED)

    @property
    def address(self) -> str:
        return self.address_edit.text().strip()

    def set_state(self, state: ConnectionState, message: str = "") -> None:
        self._state = state
        idle = state in (ConnectionState.DISCONNECTED, ConnectionState.LOST, ConnectionState.ERROR)
        self.address_edit.setEnabled(idle)
        self.button.setText(
            {ConnectionState.CONNECTING: "Cancel", ConnectionState.CONNECTED: "Disconnect"}.get(
                state, "Connect"
            )
        )
        self.status_dot.setStyleSheet(f"color: {STATE_COLORS[state]}; font-size: 16px;")
        text = state.value
        if message and state in (ConnectionState.ERROR, ConnectionState.LOST):
            text = f"{state.value}: {message}"
        self.status_text.setText(text)
        if state is ConnectionState.DISCONNECTED:
            self.identity_label.clear()

    def set_identity(self, identity: InstrumentIdentity) -> None:
        self.identity_label.setText(
            f"{identity.manufacturer} {identity.model} · SN {identity.serial} · "
            f"FW {identity.firmware}"
        )

    def _on_button(self) -> None:
        if self._state in (ConnectionState.CONNECTING, ConnectionState.CONNECTED):
            self.disconnect_requested.emit()
        else:
            self.connect_requested.emit(self.address)
