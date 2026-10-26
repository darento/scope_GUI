"""Right-hand panel: channels, acquisition summary, display tools and Pause (contracts/ui.md)."""

import math

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import CHANNEL_COLORS, CHANNELS, ScopeStatus

PANEL_WIDTH = 230
NO_VALUE = "—"

# Persistence choices: fade length in acquisitions; None = infinite, 0 = off (FR-018).
PERSISTENCE_CHOICES = {"Off": 0, "10": 10, "100": 100, "1000": 1000, "Infinite": None}

_SI_PREFIXES = ("p", "n", "µ", "m", "", "k", "M", "G")
_UNITY_INDEX = 4


def format_si(value: float, unit: str) -> str:
    """Engineering notation with up to 3 significant digits, e.g. 0.5 V -> "500 mV"."""
    if value == 0 or not math.isfinite(value):
        return f"{0 if value == 0 else value:g} {unit}"
    index = _UNITY_INDEX + math.floor(math.log10(abs(value)) / 3)
    index = max(0, min(len(_SI_PREFIXES) - 1, index))
    scaled = float(f"{value / 10 ** (3 * (index - _UNITY_INDEX)):.3g}")
    if abs(scaled) >= 1000 and index < len(_SI_PREFIXES) - 1:
        index += 1
        scaled = float(f"{scaled / 1000:.3g}")
    return f"{scaled:g} {_SI_PREFIXES[index]}{unit}"


class SidePanel(QWidget):
    hidden_changed = Signal(object)  # set[str] of channels the user unchecked
    paused_changed = Signal(bool)
    cursors_toggled = Signal(bool)
    persistence_changed = Signal(object)  # fade length, None = infinite, 0 = off
    reset_view_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumWidth(PANEL_WIDTH)
        self.setMinimumWidth(PANEL_WIDTH)

        self.checkboxes: dict[str, QCheckBox] = {}
        self.channel_labels: dict[str, QLabel] = {}

        channels_box = QGroupBox("Channels")
        channels_layout = QVBoxLayout(channels_box)
        for name in CHANNELS:
            checkbox = QCheckBox(name)
            checkbox.setChecked(True)
            checkbox.setStyleSheet(
                f"QCheckBox {{ color: {CHANNEL_COLORS[name]}; font-weight: bold; }}"
                "QCheckBox:disabled { color: #808080; }"
            )
            checkbox.toggled.connect(self._on_checkbox_toggled)
            label = QLabel(NO_VALUE)
            label.setWordWrap(True)
            row = QVBoxLayout()
            row.setSpacing(0)
            row.addWidget(checkbox)
            row.addWidget(label)
            channels_layout.addLayout(row)
            self.checkboxes[name] = checkbox
            self.channel_labels[name] = label

        self.timebase_label = QLabel(NO_VALUE)
        self.trigger_label = QLabel(f"Trigger: {NO_VALUE}")
        self.state_label = QLabel(f"State: {NO_VALUE}")
        acq_box = QGroupBox("Acquisition")
        acq_layout = QVBoxLayout(acq_box)
        acq_layout.addWidget(self.timebase_label)
        acq_layout.addWidget(self.trigger_label)
        acq_layout.addWidget(self.state_label)

        self.cursors_checkbox = QCheckBox("Cursors")
        self.cursors_checkbox.toggled.connect(self.cursors_toggled)
        self.persistence_combo = QComboBox()
        self.persistence_combo.addItems(list(PERSISTENCE_CHOICES))
        self.persistence_combo.setToolTip("Fade over this many acquisitions")
        self.persistence_combo.currentTextChanged.connect(
            lambda text: self.persistence_changed.emit(PERSISTENCE_CHOICES[text])
        )
        self.reset_view_button = QPushButton("Reset view")
        self.reset_view_button.setToolTip("Back to the scope's screen (or double-click the plot)")
        self.reset_view_button.clicked.connect(self.reset_view_requested)
        display_box = QGroupBox("Display")
        display_layout = QVBoxLayout(display_box)
        display_layout.addWidget(self.cursors_checkbox)
        persistence_row = QHBoxLayout()
        persistence_row.addWidget(QLabel("Persistence"))
        persistence_row.addWidget(self.persistence_combo, 1)
        display_layout.addLayout(persistence_row)
        display_layout.addWidget(self.reset_view_button)

        self.pause_button = QPushButton("Pause")
        self.pause_button.setCheckable(True)
        self.pause_button.toggled.connect(self._on_pause_toggled)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(channels_box)
        layout.addWidget(acq_box)
        layout.addWidget(display_box)
        pause_row = QHBoxLayout()
        pause_row.addWidget(self.pause_button)
        layout.addLayout(pause_row)
        layout.addStretch(1)

    @property
    def hidden(self) -> set[str]:
        return {name for name, box in self.checkboxes.items() if not box.isChecked()}

    @property
    def paused(self) -> bool:
        return self.pause_button.isChecked()

    def set_status(self, status: ScopeStatus) -> None:
        for name in CHANNELS:
            checkbox = self.checkboxes[name]
            label = self.channel_labels[name]
            ch = next((c for c in status.channels if c.name == name), None)
            if ch is None or not ch.enabled:
                checkbox.setEnabled(False)
                label.setText("(off)")
                continue
            checkbox.setEnabled(True)
            label.setText(
                f"{format_si(ch.volts_per_div, 'V')}/div · ofs {format_si(ch.offset, 'V')}"
                f" · {ch.coupling}"
            )
        acq = status.acquisition
        self.timebase_label.setText(f"{format_si(acq.time_per_div, 's')}/div")
        self.trigger_label.setText(f"Trigger: {acq.trigger_mode.value}")
        self.state_label.setText(f"State: {status.acq_state.value}")

    def set_not_live(self) -> None:
        """Connection lost/failed: the shown settings are the last known ones, not live."""
        self.state_label.setText("State: Not live (last known settings)")

    def clear(self) -> None:
        for name in CHANNELS:
            self.checkboxes[name].setEnabled(False)
            self.channel_labels[name].setText(NO_VALUE)
        self.timebase_label.setText(NO_VALUE)
        self.trigger_label.setText(f"Trigger: {NO_VALUE}")
        self.state_label.setText(f"State: {NO_VALUE}")
        self.pause_button.setChecked(False)  # emits paused_changed(False) only if it was paused

    def _on_checkbox_toggled(self, _checked: bool) -> None:
        self.hidden_changed.emit(self.hidden)

    def _on_pause_toggled(self, checked: bool) -> None:
        self.pause_button.setText("Resume" if checked else "Pause")
        self.paused_changed.emit(checked)
