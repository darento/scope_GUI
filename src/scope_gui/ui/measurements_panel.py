"""Measurements dock: definitions, running statistics and export (contracts/ui.md)."""

import csv
import dataclasses
import math

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
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
from ..analysis import Level, MeasurementSpec, Statistics, Summary, measure_all, si_format
from ..models import CHANNELS, Waveform
from . import measurement_dialog

GATE_CHOICES = ("Whole record", "Between cursors")
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


class _ExportSignals(QObject):
    finished = Signal(bool, str)  # ok, message for the status bar


class _CsvExport(QRunnable):
    """Writes the snapshot of the histories in a pool thread (Constitution II, research R11)."""

    def __init__(self, path: str, header: list[str], columns: list[np.ndarray]):
        super().__init__()
        self.path, self.header, self.columns = path, header, columns
        self.signals = _ExportSignals()

    def run(self) -> None:
        try:
            # UTF-8 with BOM so spreadsheet programs show Δ and µ (research R11).
            with open(self.path, "w", encoding="utf-8-sig", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(self.header)
                text = [[_csv_value(v) for v in column] for column in self.columns]
                writer.writerows(zip(*text, strict=True))
        except OSError as exc:
            self.signals.finished.emit(False, f"Export failed: {exc}")
            return
        rows = self.columns[0].size if self.columns else 0
        plural = "" if rows == 1 else "s"
        self.signals.finished.emit(True, f"Exported {rows} acquisition{plural} to {self.path}")


def _csv_value(value: float) -> str:
    return "" if math.isnan(value) else f"{value:.10g}"


class MeasurementsPanel(QWidget):
    selection_changed = Signal()  # the selected measurement (or its definition) changed
    processed = Signal()  # statistics changed: an acquisition was added or they were cleared
    gate_changed = Signal(bool)  # True: measure only between the cursors (FR-016)
    export_finished = Signal(bool, str)  # ok, message for the status bar (FR-019)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.specs: list[MeasurementSpec] = settings.load_measurements()
        self.stats: list[Statistics] = [Statistics() for _ in self.specs]
        # Trigger time of every processed acquisition, filled in step with every Statistics so
        # all histories end at the same acquisition (AcquisitionLog, research R10).
        self.trigger_log = Statistics()
        # 1.0 = every channel of the acquisition came from one trigger, 0.0 = mixed (003 R10);
        # same capacity and alignment as ``trigger_log``.
        self.coherence_log = Statistics()

        self.add_button = QPushButton("Add…")
        self.edit_button = QPushButton("Edit…")
        self.remove_button = QPushButton("Remove")
        self.clear_button = QPushButton("Clear")
        self.export_button = QPushButton("Export…")
        self.export_button.setToolTip("Save every kept value to a CSV file")
        buttons = QHBoxLayout()
        for button in (
            self.add_button,
            self.edit_button,
            self.remove_button,
            self.clear_button,
            self.export_button,
        ):
            buttons.addWidget(button)
        self.buttons_layout = buttons
        buttons.addStretch(1)

        self.gate_combo = QComboBox()
        self.gate_combo.addItems(GATE_CHOICES)
        self.gate_combo.setToolTip("Samples the measurements use")
        self.gate_combo.currentIndexChanged.connect(
            lambda index: self.gate_changed.emit(index == 1)
        )
        gate_row = QHBoxLayout()
        gate_row.addWidget(QLabel("Gate"))
        gate_row.addWidget(self.gate_combo)
        gate_row.addStretch(1)

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
        # Value columns are fitted once per update (_refresh_rows), not by ResizeToContents,
        # which re-measures every row after every cell change (~0.3 ms a cell).

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(buttons)
        layout.addLayout(gate_row)
        layout.addWidget(self.settings_note)
        layout.addWidget(self.table)

        self.add_button.clicked.connect(self._on_add)
        self.edit_button.clicked.connect(self._on_edit)
        self.table.cellDoubleClicked.connect(lambda row, _column: self._on_edit())
        self.remove_button.clicked.connect(self._on_remove)
        self.clear_button.clicked.connect(self.clear_statistics)
        self.export_button.clicked.connect(self._on_export)
        self._exports: list[_CsvExport] = []  # keep running exports alive
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
        self._refresh_rows([row])
        self.selection_changed.emit()
        self.processed.emit()

    def update_level(self, index: int, volts: float) -> None:
        """A level line of the selected measurement was dragged to ``volts`` (FR-017)."""
        row = self.selected_row
        if row is None:
            return
        spec = self.specs[row]
        field = "level" if index == 0 else "level2"
        level = getattr(spec, field)
        self.replace(row, dataclasses.replace(spec, **{field: Level(volts, False, level.edge)}))

    @property
    def gate_between_cursors(self) -> bool:
        return self.gate_combo.currentIndex() == 1

    def set_gate_between_cursors(self, on: bool) -> None:
        self.gate_combo.setCurrentIndex(1 if on else 0)

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
        self,
        waveforms: dict[str, Waveform],
        gate: tuple[float, float] | None = None,
        coherent: bool = True,
    ) -> None:
        """Measure one acquisition: exactly one entry per measurement (FR-008).

        ``coherent=False`` (channels from different triggers): measurements of more than one
        channel are recorded as missed, the others are measured as usual (003 FR-015).
        """
        first = next((waveforms[ch] for ch in CHANNELS if ch in waveforms), None)
        if first is None:
            return
        values = measure_all(self.specs, waveforms, gate)
        for spec, stats, value in zip(self.specs, self.stats, values, strict=True):
            stats.add(value if coherent or len(spec.channels) < 2 else math.nan)
        self.trigger_log.add(first.trigger_time)
        self.coherence_log.add(1.0 if coherent else 0.0)
        self._refresh_rows()
        self.processed.emit()

    def clear_statistics(self) -> None:
        for stats in self.stats:
            stats.clear()
        self.trigger_log.clear()
        self.coherence_log.clear()
        self.settings_note.hide()
        self._refresh_rows()
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

    # --- export (FR-019) -------------------------------------------------------------------------
    def ask_export_path(self) -> str:
        """Save-file dialog (replaced in tests); empty when cancelled."""
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export measurements", "measurements.csv", "CSV files (*.csv)"
        )
        return path

    def export(self, path: str) -> None:
        """Copy the histories here, write the file in the background.

        One row per kept acquisition, the trigger time first; histories end at the same
        acquisition, so a measurement added later has empty cells before it existed (R10).
        """
        times = self.trigger_log.history()
        header = ["trigger_time_s"]
        columns = [times]
        for spec, stats in zip(self.specs, self.stats, strict=True):
            unit = spec.kind.unit
            header.append(f"{spec.name} [{unit}]" if unit else spec.name)
            history = stats.history()
            column = np.full(times.size, np.nan)
            if history.size:
                column[-history.size :] = history[-times.size :]
            columns.append(column)
        job = _CsvExport(path, header, columns)
        job.signals.finished.connect(lambda ok, message: self._on_export_done(job, ok, message))
        self._exports.append(job)
        QThreadPool.globalInstance().start(job)

    def _on_export(self) -> None:
        path = self.ask_export_path()
        if path:
            self.export(path)

    def _on_export_done(self, job: _CsvExport, ok: bool, message: str) -> None:
        if job in self._exports:
            self._exports.remove(job)
        self.export_finished.emit(ok, message)

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
        self._refresh_rows()
        self.table.blockSignals(False)
        self._update_buttons()

    def _refresh_rows(self, rows=None) -> None:
        """Set the cells whose text changed, then fit the value columns."""
        for row in range(len(self.specs)) if rows is None else rows:
            for column, text in enumerate(self._row_texts(row)):
                item = self.table.item(row, column)
                if item.text() != text:
                    item.setText(text)
        for column in range(1, len(COLUMNS)):
            self.table.resizeColumnToContents(column)

    def _row_texts(self, row: int) -> tuple[str, ...]:
        spec = self.specs[row]
        s = self.stats[row].summary()
        unit = spec.kind.unit
        return (
            spec.name,
            format_value(s.last, unit),
            format_value(s.mean, unit),
            format_value(s.std, unit),
            format_value(s.minimum, unit),
            format_value(s.maximum, unit),
            str(s.count),
            str(s.missed),
        )

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
