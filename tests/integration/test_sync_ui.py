"""Synchronized capture in the window: switch, indicators, pause and close (003 contracts/ui.md)."""

from scope_gui.analysis import Kind, Level, MeasurementSpec
from scope_gui.models import ConnectionState

SYNC_TEXT = "Driving the scope: synchronized capture"


def switch_on(window, qtbot):
    window.side_panel.sync_checkbox.click()
    qtbot.waitUntil(lambda: window.view.synchronized, timeout=3000)


def test_switch_only_while_connected_and_off_at_start(running_bench, qtbot):
    window, scope = running_bench()
    box = window.side_panel.sync_checkbox
    assert box.isEnabled() and not box.isChecked()
    window.connection_bar.button.click()  # disconnect
    qtbot.waitUntil(lambda: window._state is ConnectionState.DISCONNECTED, timeout=3000)
    assert not box.isEnabled()
    window.connection_bar.button.click()
    qtbot.waitUntil(lambda: window._state is ConnectionState.CONNECTED, timeout=3000)
    assert box.isEnabled() and not box.isChecked()


def test_ticking_shows_the_indicator_and_unticking_restores(running_bench, qtbot):
    window, scope = running_bench()
    switch_on(window, qtbot)
    assert window.sync_label.isVisibleTo(window) and window.sync_label.text() == SYNC_TEXT
    qtbot.waitUntil(
        lambda: window.side_panel.trigger_label.text() == "Trigger: Auto (synchronized)",
        timeout=3000,
    )
    window.side_panel.sync_checkbox.click()
    qtbot.waitUntil(lambda: not window.view.synchronized, timeout=3000)
    assert not window.sync_label.isVisibleTo(window)
    qtbot.waitUntil(lambda: scope.trigger_mode == "AUTO", timeout=3000)
    assert scope.controls[-1] == "TRMD AUTO"
    qtbot.waitUntil(lambda: window.side_panel.trigger_label.text() == "Trigger: Auto", timeout=3000)


def test_worker_ending_the_mode_unticks_and_tells_why(running_bench, qtbot):
    window, scope = running_bench(mode="NORM", triggers=False)
    switch_on(window, qtbot)
    scope._set_mode("AUTO")  # changed on the front panel
    qtbot.waitUntil(lambda: not window.side_panel.sync_checkbox.isChecked(), timeout=3000)
    assert not window.sync_label.isVisibleTo(window)
    assert "synchronized capture switched off" in window.statusBar().currentMessage()


def test_no_settings_note_for_the_apps_own_trigger_mode(running_bench, qtbot):
    window, scope = running_bench()
    panel = window.measurements_panel
    panel.add(MeasurementSpec(Kind.DELTA_T, "C1", Level(1.25), "C2", Level(0.03)))
    switch_on(window, qtbot)
    qtbot.waitUntil(lambda: panel.trigger_log.size >= 5, timeout=5000)
    assert not panel.settings_note_visible
    assert panel.stats[0].summary().count >= 1  # cross-channel values are kept: coherent


def test_pause_stops_arming_and_resume_rearms(running_bench, qtbot):
    window, scope = running_bench()
    switch_on(window, qtbot)
    qtbot.waitUntil(lambda: scope.controls.count("ARM") >= 3, timeout=3000)
    window.side_panel.pause_button.click()
    qtbot.wait(150)
    arms = scope.controls.count("ARM")
    qtbot.wait(300)
    assert scope.controls.count("ARM") == arms
    window.side_panel.pause_button.click()
    qtbot.waitUntil(lambda: scope.controls.count("ARM") > arms, timeout=3000)


def test_closing_the_window_restores_the_trigger_mode(running_bench, qtbot):
    window, scope = running_bench(mode="NORM")
    switch_on(window, qtbot)
    qtbot.waitUntil(lambda: scope.controls.count("ARM") >= 2, timeout=3000)
    window.close()
    assert scope.trigger_mode == "NORM"
    assert scope.controls[-1] == "TRMD NORM"
