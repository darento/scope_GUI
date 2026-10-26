"""Measurements dock: definitions, table, statistics and the add/edit dialog (contracts/ui.md)."""

import math

import numpy as np
import pytest

from scope_gui import settings
from scope_gui.analysis import Edge, Kind, Level, MeasurementSpec
from scope_gui.models import Waveform
from scope_gui.ui.measurement_dialog import MeasurementDialog
from scope_gui.ui.measurements_panel import COLUMNS, MeasurementsPanel, format_value

DT = 1e-9


def acquisition(peak: float = 2.0, trigger_time: float = 1.0, with_c2: bool = True):
    """C1: a ramp 0 -> peak over 100 ns; C2 (optional): a 0/1 V step at 50 ns."""
    t = np.arange(100) * DT
    waves = {"C1": Waveform("C1", (t / t[-1] * peak).astype(np.float32), 0.0, DT, trigger_time, 0)}
    if with_c2:
        step = (t >= 50e-9).astype(np.float32)
        waves["C2"] = Waveform("C2", step, 0.0, DT, trigger_time, 0)
    return waves


MAX_C1 = MeasurementSpec(Kind.MAXIMUM, "C1")
MAX_C2 = MeasurementSpec(Kind.MAXIMUM, "C2")
TIME_C2 = MeasurementSpec(Kind.TIME_AT_LEVEL, "C2", Level(0.5))


@pytest.fixture
def panel(qtbot):
    widget = MeasurementsPanel()
    qtbot.addWidget(widget)
    return widget


def answering(panel, monkeypatch, spec):
    monkeypatch.setattr(panel, "ask_spec", lambda current=None: spec)


def test_add_via_dialog_appends_named_row(panel, monkeypatch):
    answering(panel, monkeypatch, MAX_C1)
    panel.add_button.click()
    assert panel.table.rowCount() == 1
    assert panel.cell_text(0, "Measurement") == "Maximum C1"
    assert panel.selected_spec == MAX_C1
    assert [panel.table.horizontalHeaderItem(i).text() for i in range(8)] == list(COLUMNS)


def test_cancelled_dialog_adds_nothing(panel, monkeypatch):
    answering(panel, monkeypatch, None)
    panel.add_button.click()
    assert panel.table.rowCount() == 0


def test_one_value_per_measurement_per_acquisition(panel):
    panel.add(MAX_C1)
    panel.add(TIME_C2)
    for peak in (1.0, 2.0, 3.0):
        panel.process(acquisition(peak))
    assert [s.size for s in panel.stats] == [3, 3]
    assert panel.trigger_log.size == 3
    assert panel.cell_text(0, "Last") == "3 V"
    assert panel.cell_text(0, "Mean") == "2 V"
    assert panel.cell_text(0, "σ") == "1 V"
    assert panel.cell_text(0, "Min") == "1 V"
    assert panel.cell_text(0, "Max") == "3 V"
    assert panel.cell_text(0, "N") == "3"
    assert panel.cell_text(1, "Last") == "49.5 ns"


def test_missed_value_counts_as_missed_only(panel):
    panel.add(MAX_C2)
    panel.process(acquisition())
    panel.process(acquisition(with_c2=False))  # C2 switched off
    assert (panel.cell_text(0, "N"), panel.cell_text(0, "Missed")) == ("1", "1")
    assert panel.cell_text(0, "Last") == "—"
    assert panel.cell_text(0, "Mean") == "1 V"


def test_undefined_values_show_a_dash(panel):
    panel.add(MAX_C1)
    for column in ("Last", "Mean", "σ", "Min", "Max"):
        assert panel.cell_text(0, column) == "—"
    assert panel.cell_text(0, "N") == "0"


def test_value_formats():
    assert format_value(1.2345e-10, "s") == "123.5 ps"
    assert format_value(42.123, "%") == "42.12 %"
    assert format_value(7.0, "") == "7"
    assert format_value(math.nan, "V") == "—"


def test_clear_restarts_all_and_hides_note(panel):
    panel.add(MAX_C1)
    panel.add(MAX_C2)
    panel.process(acquisition())
    panel.set_settings_changed()
    assert panel.settings_note_visible
    panel.clear_button.click()
    assert [s.size for s in panel.stats] == [0, 0]
    assert panel.trigger_log.size == 0
    assert not panel.settings_note_visible


def test_settings_note_only_with_values(panel):
    panel.add(MAX_C1)
    panel.set_settings_changed()
    assert not panel.settings_note_visible


def test_edit_restarts_only_that_measurement(panel, monkeypatch):
    panel.add(MAX_C1)
    panel.add(MAX_C2)
    panel.process(acquisition())
    panel.table.selectRow(1)
    answering(panel, monkeypatch, TIME_C2)
    panel.edit_button.click()
    assert panel.specs == [MAX_C1, TIME_C2]
    assert [s.size for s in panel.stats] == [1, 0]
    assert panel.cell_text(1, "Measurement") == "Time C2 ↑ 500 mV"


def test_remove_drops_row_and_statistics(panel):
    panel.add(MAX_C1)
    panel.add(MAX_C2)
    panel.process(acquisition())
    panel.table.selectRow(0)
    panel.remove_button.click()
    assert panel.specs == [MAX_C2]
    assert len(panel.stats) == 1 and panel.stats[0].size == 1
    assert panel.cell_text(0, "Measurement") == "Maximum C2"


def test_list_saved_and_restored(panel, qtbot):
    panel.add(MAX_C1)
    panel.add(TIME_C2)
    assert settings.load_measurements() == [MAX_C1, TIME_C2]
    again = MeasurementsPanel()
    qtbot.addWidget(again)
    assert again.specs == [MAX_C1, TIME_C2]
    assert all(s.size == 0 for s in again.stats)  # statistics are not remembered
    assert again.selected_spec == MAX_C1


def test_selection_signal(panel, qtbot):
    panel.add(MAX_C1)
    panel.add(MAX_C2)
    with qtbot.waitSignal(panel.selection_changed):
        panel.table.selectRow(0)
    assert panel.selected_spec == MAX_C1


# --- dialog ---------------------------------------------------------------------------------------


@pytest.fixture
def dialog(qtbot):
    widget = MeasurementDialog()
    qtbot.addWidget(widget)
    widget.show()
    return widget


def choose(dialog, kind: Kind):
    dialog.kind_combo.setCurrentIndex(list(Kind).index(kind))


def test_dialog_rows_follow_the_type(dialog):
    choose(dialog, Kind.AMPLITUDE)
    assert not dialog.level_editor.isVisible()
    assert not dialog.source2_combo.isVisible()
    choose(dialog, Kind.TIME_AT_LEVEL)
    assert dialog.level_editor.isVisible()
    assert not dialog.level2_editor.isVisible()
    choose(dialog, Kind.DELTA_T)
    assert dialog.level2_editor.isVisible() and dialog.source2_combo.isVisible()


def test_dialog_percent_uses_leading_trailing(dialog):
    editor = dialog.level_editor
    editor.unit_combo.setCurrentText("%")
    assert [editor.edge_combo.itemText(i) for i in range(2)] == ["Leading", "Trailing"]
    editor.unit_combo.setCurrentText("V")
    assert [editor.edge_combo.itemText(i) for i in range(2)] == ["Rising", "Falling"]


def test_dialog_builds_the_spec(dialog):
    choose(dialog, Kind.DELTA_T)
    dialog.source_combo.setCurrentText("C2")
    dialog.level_editor.unit_combo.setCurrentText("mV")
    dialog.level_editor.value_edit.setText("30")
    dialog.source2_combo.setCurrentText("C4")
    dialog.level2_editor.unit_combo.setCurrentText("V")
    dialog.level2_editor.value_edit.setText("-0.4")
    dialog.level2_editor.edge_combo.setCurrentIndex(1)
    spec = dialog.spec()
    assert spec == MeasurementSpec(
        Kind.DELTA_T, "C2", Level(0.030), "C4", Level(-0.4, edge=Edge.FALLING)
    )
    dialog.level_editor.unit_combo.setCurrentText("%")
    dialog.level_editor.value_edit.setText("20")
    assert dialog.spec().level == Level(0.2, True, Edge.RISING)


def test_dialog_ok_disabled_until_valid(dialog):
    choose(dialog, Kind.TIME_AT_LEVEL)
    dialog.level_editor.value_edit.setText("abc")
    assert not dialog.ok_button.isEnabled()
    dialog.level_editor.unit_combo.setCurrentText("%")
    dialog.level_editor.value_edit.setText("150")
    assert not dialog.ok_button.isEnabled()
    dialog.level_editor.value_edit.setText("50")
    assert dialog.ok_button.isEnabled()
    choose(dialog, Kind.AMPLITUDE)  # no level needed: the invalid hidden field does not matter
    dialog.level_editor.value_edit.setText("abc")
    assert dialog.ok_button.isEnabled()


def test_dialog_edits_an_existing_spec(qtbot):
    spec = MeasurementSpec(Kind.DELTA_T, "C2", Level(0.2, True), "C3", Level(0.2, True))
    dialog = MeasurementDialog(spec)
    qtbot.addWidget(dialog)
    assert dialog.spec() == spec
    assert dialog.windowTitle() == "Edit measurement"
