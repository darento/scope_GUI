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
    assert format_value(0.99999994, "V") == "1 V"  # not "1000 mV"
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


# --- gate and level lines (US4) -------------------------------------------------------------------


def test_gate_combo(panel, qtbot):
    assert [panel.gate_combo.itemText(i) for i in range(2)] == ["Whole record", "Between cursors"]
    assert not panel.gate_between_cursors
    with qtbot.waitSignal(panel.gate_changed) as signal:
        panel.gate_combo.setCurrentIndex(1)
    assert signal.args == [True]
    assert panel.gate_between_cursors


def test_process_uses_the_gate(panel):
    panel.add(MAX_C1)
    panel.process(acquisition(peak=2.0), gate=(0.0, 49e-9))  # first half of the ramp only
    assert panel.stats[0].last == pytest.approx(2.0 * 49 / 99, rel=1e-4)


def test_update_level_replaces_only_the_selected_measurement(panel):
    dt = MeasurementSpec(Kind.DELTA_T, "C2", Level(0.03), "C4", Level(-0.4, edge=Edge.FALLING))
    panel.add(MAX_C1)
    panel.add(dt)
    panel.process(acquisition())
    panel.table.selectRow(1)
    panel.update_level(1, -0.25)
    assert panel.specs[1].level2 == Level(-0.25, edge=Edge.FALLING)
    assert panel.specs[1].level == Level(0.03)
    assert [s.size for s in panel.stats] == [1, 0]
    assert panel.cell_text(1, "Measurement") == "Δt C2 ↑ 30 mV → C4 ↓ -250 mV"
    assert settings.load_measurements()[1] == panel.specs[1]


# --- wiring in the main window -----------------------------------------------------------------


@pytest.fixture
def window(qtbot):
    from scope_gui.ui.main_window import MainWindow

    widget = MainWindow("192.168.0.9")
    qtbot.addWidget(widget)
    yield widget
    widget.close()


def test_window_has_measurements_dock_and_view_menu(window):
    assert window.measurements_dock.widget() is window.measurements_panel
    actions = [a.text() for a in window.view_menu.actions()]
    assert "Measurements" in actions


def test_gate_between_cursors_switches_cursors_on(window):
    panel, plot = window.measurements_panel, window.scope_plot
    panel.set_gate_between_cursors(True)
    assert window.side_panel.cursors_checkbox.isChecked()
    assert plot.cursors_visible and plot.gate_visible
    window.side_panel.cursors_checkbox.setChecked(False)  # no cursors: back to whole record
    assert not panel.gate_between_cursors and plot.gate() is None


def test_selected_measurement_drives_level_lines(window):
    from test_scope_plot import make_status

    window.scope_plot.set_status(make_status())
    panel = window.measurements_panel
    panel.add(MAX_C1)
    assert window.scope_plot.level_lines == []
    panel.add(TIME_C2)  # selected: one volt level on C2
    assert len(window.scope_plot.level_lines) == 1
    window.scope_plot.level_dragged.emit(0, 0.25)
    assert panel.specs[1].level == Level(0.25)
    assert window.scope_plot.level_lines[0].label.format == "C2 ↑ 250 mV"


# --- export (US5) ---------------------------------------------------------------------------------


def read_csv(path):
    import csv

    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM for spreadsheet programs
    with open(path, encoding="utf-8-sig", newline="") as file:
        return list(csv.reader(file))


def export(panel, qtbot, path):
    with qtbot.waitSignal(panel.export_finished, timeout=30000) as signal:
        panel.export(str(path))
    return signal.args


def test_export_rows_columns_and_missed_cells(panel, qtbot, tmp_path, monkeypatch):
    panel.add(MAX_C1)
    panel.add(MAX_C2)
    for i in range(200):
        panel.process(acquisition(trigger_time=i, with_c2=i % 10 != 0))
    panel.add(TIME_C2)  # added later: empty before it existed (US5-2)
    for i in range(200, 500):
        panel.process(acquisition(trigger_time=i))
    path = tmp_path / "run.csv"
    monkeypatch.setattr(panel, "ask_export_path", lambda: str(path))
    with qtbot.waitSignal(panel.export_finished, timeout=30000) as signal:
        panel.export_button.click()
    ok, message = signal.args
    assert ok and str(path) in message and "500 acquisitions" in message
    rows = read_csv(path)
    assert rows[0] == ["trigger_time_s", "Maximum C1 [V]", "Maximum C2 [V]", "Time C2 ↑ 500 mV [s]"]
    body = rows[1:]
    assert len(body) == 500
    assert [float(r[0]) for r in body] == list(range(500))
    assert body[0][2] == "" and body[1][2] == "1"  # missed: C2 off in acquisition 0
    assert all(r[3] == "" for r in body[:200])
    assert float(body[200][3]) == pytest.approx(49.5e-9)


def test_cancelled_export_writes_nothing(panel, monkeypatch, tmp_path):
    monkeypatch.setattr(panel, "ask_export_path", lambda: "")
    panel.export_button.click()
    assert list(tmp_path.iterdir()) == []


def test_large_export_does_not_block(panel, qtbot, tmp_path):
    import time

    n = 100_000
    for k in range(10):
        panel.add(MeasurementSpec(Kind.MAXIMUM, "C1"))
        stats = panel.stats[-1]
        stats._buffer[:] = np.arange(n) + k
        stats._next, stats._size = 0, n
    panel.trigger_log._buffer[:] = np.arange(n)
    panel.trigger_log._next, panel.trigger_log._size = 0, n
    path = tmp_path / "big.csv"
    with qtbot.waitSignal(panel.export_finished, timeout=60000) as signal:
        start = time.perf_counter()
        panel.export(str(path))
        assert time.perf_counter() - start < 0.2  # the write runs in a pool thread (SC-006)
    assert signal.args[0]
    rows = read_csv(path)
    assert len(rows) == n + 1 and len(rows[0]) == 11
    assert rows[-1][:3] == ["99999", "99999", "100000"]


def test_failed_export_reports_instead_of_raising(panel, qtbot, tmp_path):
    panel.add(MAX_C1)
    panel.process(acquisition())
    ok, message = export(panel, qtbot, tmp_path / "missing-folder" / "x.csv")
    assert not ok and message.startswith("Export failed")


def test_export_result_in_status_bar(window, qtbot, tmp_path):
    panel = window.measurements_panel
    panel.add(MAX_C1)
    panel.process(acquisition())
    export(panel, qtbot, tmp_path / "one.csv")
    assert "Exported 1 acquisition to" in window.statusBar().currentMessage()


# --- histogram dock (US3) -------------------------------------------------------------------------


def test_histogram_dock_follows_the_selected_measurement(window, qtbot):
    from test_scope_plot import make_waveform

    window.show()
    qtbot.waitExposed(window)
    assert window.histogram_dock.widget() is window.histogram_panel
    assert "Histogram" in [a.text() for a in window.view_menu.actions()]
    panel, histogram = window.measurements_panel, window.histogram_panel
    panel.add(MAX_C1)
    panel.add(TIME_C2)
    for _ in range(5):
        panel.process({"C1": make_waveform("C1")})
    assert histogram._specs == [MAX_C1, TIME_C2] and histogram._selected == 1
    panel.table.selectRow(0)
    assert histogram._selected == 0
    assert histogram.stats_label.text().startswith("N 5 · outside 0")


def test_shown_acquisition_is_measured_in_the_next_event_loop_turn(window, qtbot):
    """Drawing and analysis are separate turns, and the worker is released only after both."""
    from test_scope_plot import make_status, make_waveform

    released = []
    window.worker.waveforms_consumed = lambda: released.append(True)
    window.scope_plot.set_status(make_status())
    window.measurements_panel.add(MAX_C1)
    window._on_waveforms({"C1": make_waveform("C1")})
    assert window.measurements_panel.stats[0].summary().count == 0 and released == []
    qtbot.waitUntil(lambda: released == [True], timeout=1000)
    assert window.measurements_panel.stats[0].summary().count == 1
    window.side_panel.pause_button.click()
    window._on_waveforms({"C1": make_waveform("C1")})  # paused: released at once, not measured
    assert released == [True, True]
    qtbot.wait(20)
    assert window.measurements_panel.stats[0].summary().count == 1
