"""Measurements dock: definitions, running statistics and export (contracts/ui.md)."""

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import settings
from ..analysis import MeasurementSpec, Statistics, Summary, measure_all, si_format
from ..models import CHANNELS, Waveform
from . import measurement_dialog

COLUMNS = ("Measurement", "Last", "Mean", "σ", "Min", "Max", "N", "Missed")
SETTINGS_NOTE = "⚠ Scope settings changed during this run"
_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def format_value(value: float, unit: str) -> str:
    """Table text: SI with 4 significant digits, % with 2 decimals, counts plain; "—" if none."""
    if not math.isfinite(value):
        return "—"
    if unit == "%":
        return f"{value:.2f} %"
    if not unit:
        return f"{value:.4g}"
    return si_format(value, unit)


class MeasurementsPanel(QWidget):
    selection_changed = Signal()  # the selected measurement (or its definition) changed
    processed = Signal()  # statistics changed: an acquisition was added or they were cleared

    def __init__(self, parent=None):
        super().__init__(parent)
        self.specs: list[MeasurementSpec] = settings.load_measurements()
        self.stats: list[Statistics] = [Statistics() for _ in self.specs]
        # Trigger time of every processed acquisition, filled in step with every Statistics so
        # all histories end at the same acquisition (AcquisitionLog, research R10).
        self.trigger_log = Statistics()

        self.add_button = QPushButton("Add…")
        self.edit_button = QPushButton("Edit…")
        self.remove_button = QPushButton("Remove")
        self.clear_button = QPushButton("Clear")
        buttons = QHBoxLayout()
        for button in (self.add_button, self.edit_button, self.remove_button, self.clear_button):
            buttons.addWidget(button)
        self.buttons_layout = buttons
        buttons.addStretch(1)

        self.settings_note = QLabel(SETTINGS_NOTE)
        self.settings_note.setStyleSheet("color: #f0a020;")
        self.settings_note.hide()

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(buttons)
        layout.addWidget(self.settings_note)
        layout.addWidget(self.table)

        self.add_button.clicked.connect(self._on_add)
        self.edit_button.clicked.connect(self._on_edit)
        self.table.cellDoubleClicked.connect(lambda row, _column: self._on_edit())
        self.remove_button.clicked.connect(self._on_remove)
        self.clear_button.clicked.connect(self.clear_statistics)
        self.table.itemSelectionChanged.connect(self._on_selection)

        self._rebuild_table()
        if self.specs:
            self.table.selectRow(0)
        self._update_buttons()

    # --- definitions ----------------------------------------------------------------------------
    def ask_spec(self, spec: MeasurementSpec | None = None) -> MeasurementSpec | None:
        """Open the add/edit dialog (replaced in tests)."""
        return measurement_dialog.ask_measurement(self, spec)

    @property
    def selected_row(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    @property
    def selected_spec(self) -> MeasurementSpec | None:
        row = self.selected_row
        return None if row is None else self.specs[row]

    def add(self, spec: MeasurementSpec) -> None:
        self.specs.append(spec)
        self.stats.append(Statistics())
        self._save()
        self._rebuild_table()
        self.table.selectRow(len(self.specs) - 1)

    def replace(self, row: int, spec: MeasurementSpec) -> None:
        """New definition for one measurement; only its statistics restart (FR-010)."""
        self.specs[row] = spec
        self.stats[row] = Statistics()
        self._save()
        self._refresh_row(row)
        self.selection_changed.emit()
        self.processed.emit()

    def remove(self, row: int) -> None:
        del self.specs[row]
        del self.stats[row]
        self._save()
        self._rebuild_table()
        if self.specs:
            self.table.selectRow(min(row, len(self.specs) - 1))
        else:
            self.selection_changed.emit()
        self.processed.emit()

    # --- statistics -----------------------------------------------------------------------------
    def process(
        self, waveforms: dict[str, Waveform], gate: tuple[float, float] | None = None
    ) -> None:
        """Measure one acquisition: exactly one entry per measurement (FR-008)."""
        first = next((waveforms[ch] for ch in CHANNELS if ch in waveforms), None)
        if first is None:
            return
        values = measure_all(self.specs, waveforms, gate)
        for stats, value in zip(self.stats, values, strict=True):
            stats.add(value)
        self.trigger_log.add(first.trigger_time)
        for row in range(len(self.specs)):
            self._refresh_row(row)
        self.processed.emit()

    def clear_statistics(self) -> None:
        for stats in self.stats:
            stats.clear()
        self.trigger_log.clear()
        self.settings_note.hide()
        for row in range(len(self.specs)):
            self._refresh_row(row)
        self.processed.emit()

    def set_settings_changed(self) -> None:
        """The scope's settings changed; warn while the statistics hold values (FR-022)."""
        if self.trigger_log.size:
            self.settings_note.show()

    @property
    def settings_note_visible(self) -> bool:
        return not self.settings_note.isHidden()

    def summary(self, row: int) -> Summary:
        return self.stats[row].summary()

    # --- table ----------------------------------------------------------------------------------
    def _rebuild_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.specs))
        for row in range(len(self.specs)):
            for column in range(len(COLUMNS)):
                item = QTableWidgetItem()
                if column:
                    item.setTextAlignment(_RIGHT)
                self.table.setItem(row, column, item)
            self._refresh_row(row)
        self.table.blockSignals(False)
        self._update_buttons()

    def _refresh_row(self, row: int) -> None:
        spec = self.specs[row]
        s = self.stats[row].summary()
        unit = spec.kind.unit
        texts = (
            spec.name,
            format_value(s.last, unit),
            format_value(s.mean, unit),
            format_value(s.std, unit),
            format_value(s.minimum, unit),
            format_value(s.maximum, unit),
            str(s.count),
            str(s.missed),
        )
        for column, text in enumerate(texts):
            self.table.item(row, column).setText(text)

    def cell_text(self, row: int, column: str) -> str:
        return self.table.item(row, COLUMNS.index(column)).text()

    # --- slots ----------------------------------------------------------------------------------
    def _on_add(self) -> None:
        spec = self.ask_spec(None)
        if spec is not None:
            self.add(spec)

    def _on_edit(self) -> None:
        row = self.selected_row
        if row is None:
            return
        spec = self.ask_spec(self.specs[row])
        if spec is not None and spec != self.specs[row]:
            self.replace(row, spec)

    def _on_remove(self) -> None:
        row = self.selected_row
        if row is not None:
            self.remove(row)

    def _on_selection(self) -> None:
        self._update_buttons()
        self.selection_changed.emit()

    def _update_buttons(self) -> None:
        selected = self.selected_row is not None
        self.edit_button.setEnabled(selected)
        self.remove_button.setEnabled(selected)

    def _save(self) -> None:
        settings.save_measurements(self.specs)
