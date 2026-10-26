"""Add/Edit measurement dialog (specs/002-waveform-analysis/contracts/ui.md)."""

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QWidget,
)

from ..analysis import Edge, Kind, Level, MeasurementSpec
from ..models import CHANNELS

# Definitions shown as tooltips (data-model.md "Kind").
DEFINITIONS = {
    Kind.DELTA_T: "First crossing of level 2 on source 2 minus first crossing of level 1 on "
    "source 1, interpolated between samples",
    Kind.TIME_AT_LEVEL: "First crossing of the level, relative to the trigger (t = 0)",
    Kind.EDGE_COUNT: "Number of crossings of the level with its edge",
    Kind.AMPLITUDE: "Top − base (negative for negative pulses)",
    Kind.BASE: "Low level of square-like signals, baseline of pulses (whole record)",
    Kind.TOP: "High level of square-like signals, peak of pulses (inside the gate)",
    Kind.MAXIMUM: "Highest sample in the gate",
    Kind.MINIMUM: "Lowest sample in the gate",
    Kind.PK_PK: "Maximum − minimum in the gate",
    Kind.MEAN: "Mean of the samples in the gate",
    Kind.AREA: "Integral of (signal − base) over the gate, in volt-seconds",
    Kind.RISE_TIME: "First complete leading edge, 10 % → 90 % of base → top",
    Kind.FALL_TIME: "First trailing 90 % crossing → next trailing 10 % crossing",
    Kind.WIDTH: "First leading 50 % crossing → next trailing 50 % crossing",
    Kind.PERIOD: "Mean spacing of leading 50 % crossings (at least two needed)",
    Kind.FREQUENCY: "1 / period",
    Kind.DUTY_CYCLE: "Mean time from a leading to the next trailing 50 % crossing / period",
}

UNITS = {"V": 1.0, "mV": 1e-3, "%": None}


class LevelEditor(QWidget):
    """Value, unit (V, mV or % of amplitude) and edge of one level."""

    def __init__(self, level: Level, parent=None):
        super().__init__(parent)
        self.value_edit = QLineEdit()
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(list(UNITS))
        self.edge_combo = QComboBox()
        self.edge_combo.addItems(["", ""])
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.value_edit, 1)
        layout.addWidget(self.unit_combo)
        layout.addWidget(self.edge_combo)
        self.unit_combo.currentTextChanged.connect(self._update_edge_names)
        self.set_level(level)

    def set_level(self, level: Level) -> None:
        if level.relative:
            unit, shown = "%", level.value * 100
        elif level.value != 0 and abs(level.value) < 1:
            unit, shown = "mV", level.value * 1e3
        else:
            unit, shown = "V", level.value
        self.unit_combo.setCurrentText(unit)
        self.value_edit.setText(f"{shown:g}")
        self.edge_combo.setCurrentIndex(0 if level.edge is Edge.RISING else 1)
        self._update_edge_names()

    def level(self) -> Level | None:
        """The entered level, or None while the value is not valid."""
        try:
            value = float(self.value_edit.text().replace(",", "."))
        except ValueError:
            return None
        if not math.isfinite(value):
            return None
        edge = Edge.RISING if self.edge_combo.currentIndex() == 0 else Edge.FALLING
        scale = UNITS[self.unit_combo.currentText()]
        if scale is None:
            if not 0 <= value <= 100:
                return None
            return Level(value / 100, True, edge)
        return Level(value * scale, False, edge)

    def _update_edge_names(self) -> None:
        relative = self.unit_combo.currentText() == "%"
        names = ("Leading", "Trailing") if relative else ("Rising", "Falling")
        for index, name in enumerate(names):
            self.edge_combo.setItemText(index, name)


class MeasurementDialog(QDialog):
    def __init__(self, spec: MeasurementSpec | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit measurement" if spec else "Add measurement")
        spec = spec or MeasurementSpec(Kind.DELTA_T, "C1", Level(0.5), "C2", Level(0.5))

        self.kind_combo = QComboBox()
        for index, kind in enumerate(Kind):
            self.kind_combo.addItem(kind.value, kind)
            self.kind_combo.setItemData(index, DEFINITIONS[kind], Qt.ItemDataRole.ToolTipRole)
        self.source_combo = QComboBox()
        self.source_combo.addItems(CHANNELS)
        self.level_editor = LevelEditor(spec.level)
        self.source2_combo = QComboBox()
        self.source2_combo.addItems(CHANNELS)
        self.level2_editor = LevelEditor(spec.level2)

        self.form = QFormLayout()
        self.form.addRow("Type", self.kind_combo)
        self.form.addRow("Source", self.source_combo)
        self.form.addRow("Level", self.level_editor)
        self.form.addRow("Source 2", self.source2_combo)
        self.form.addRow("Level 2", self.level2_editor)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.form.addRow(self.buttons)
        self.setLayout(self.form)

        self.kind_combo.setCurrentIndex(list(Kind).index(spec.kind))
        self.source_combo.setCurrentText(spec.source)
        self.source2_combo.setCurrentText(spec.source2)

        self.kind_combo.currentIndexChanged.connect(self._update)
        for editor in (self.level_editor, self.level2_editor):
            editor.value_edit.textChanged.connect(self._update)
            editor.unit_combo.currentTextChanged.connect(self._update)
        self._update()

    @property
    def kind(self) -> Kind:
        return self.kind_combo.currentData()

    def spec(self) -> MeasurementSpec | None:
        """The entered measurement, or None while a needed level is invalid."""
        kind = self.kind
        level, level2 = Level(), Level()
        if kind.levels >= 1:
            level = self.level_editor.level()
        if kind.levels >= 2:
            level2 = self.level2_editor.level()
        if level is None or level2 is None:
            return None
        source2 = self.source2_combo.currentText() if kind is Kind.DELTA_T else "C2"
        return MeasurementSpec(kind, self.source_combo.currentText(), level, source2, level2)

    def _update(self) -> None:
        levels = self.kind.levels
        self.form.setRowVisible(self.level_editor, levels >= 1)
        self.form.setRowVisible(self.source2_combo, levels >= 2)
        self.form.setRowVisible(self.level2_editor, levels >= 2)
        self.kind_combo.setToolTip(DEFINITIONS[self.kind])
        self.ok_button.setEnabled(self.spec() is not None)


def ask_measurement(parent: QWidget | None, spec: MeasurementSpec | None = None):
    """Show the dialog; the new definition, or None when cancelled."""
    dialog = MeasurementDialog(spec, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.spec()
