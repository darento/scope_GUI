import pytest

from scope_gui.models import (
    AcqState,
    AcquisitionSettings,
    ChannelSettings,
    ScopeStatus,
    TriggerMode,
)
from scope_gui.ui.side_panel import SidePanel, format_si


def make_status(
    enabled=("C1", "C4"),
    mode=TriggerMode.AUTO,
    state=AcqState.ACQUIRING,
    time_per_div=100e-9,
) -> ScopeStatus:
    channels = tuple(
        ChannelSettings(
            name=name,
            enabled=name in enabled,
            volts_per_div=0.5,
            offset=-0.485,
            coupling="D1M",
        )
        for name in ("C1", "C2", "C3", "C4")
    )
    acq = AcquisitionSettings(
        time_per_div=time_per_div,
        trigger_delay=0.0,
        trigger_mode=mode,
        grid_mode="SINGLE",
    )
    return ScopeStatus(channels=channels, acquisition=acq, acq_state=state, read_at=0.0)


@pytest.fixture
def panel(qtbot):
    widget = SidePanel()
    qtbot.addWidget(widget)
    return widget


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (5e-6, "s", "5 µs"),
        (100e-9, "s", "100 ns"),
        (0.5, "V", "500 mV"),
        (1, "V", "1 V"),
        (-3.01, "V", "-3.01 V"),
        (-0.485, "V", "-485 mV"),
        (0, "V", "0 V"),
        (2.5e-3, "s", "2.5 ms"),
        (0.9999, "V", "1 V"),
        (1e3, "Hz", "1 kHz"),
        (50e-12, "s", "50 ps"),
    ],
)
def test_format_si(value, unit, expected):
    assert format_si(value, unit) == expected


def test_set_status_fills_channel_rows(panel):
    panel.set_status(make_status())
    assert panel.channel_labels["C1"].text() == "500 mV/div · ofs -485 mV · D1M"
    assert panel.checkboxes["C1"].isEnabled()
    assert panel.checkboxes["C4"].isEnabled()
    for name in ("C2", "C3"):
        assert panel.channel_labels[name].text() == "(off)"
        assert not panel.checkboxes[name].isEnabled()


def test_set_status_fills_acquisition_labels(panel):
    panel.set_status(make_status(mode=TriggerMode.NORM, state=AcqState.WAITING_FOR_TRIGGER))
    assert panel.timebase_label.text() == "100 ns/div"
    assert panel.trigger_label.text() == "Trigger: Normal"
    assert panel.state_label.text() == "State: Waiting for trigger"


def test_checkboxes_checked_by_default(panel):
    assert all(box.isChecked() for box in panel.checkboxes.values())
    assert panel.hidden == set()


def test_unchecking_emits_hidden_changed(panel, qtbot):
    panel.set_status(make_status())
    with qtbot.waitSignal(panel.hidden_changed) as blocker:
        panel.checkboxes["C4"].setChecked(False)
    assert blocker.args == [{"C4"}]
    assert panel.hidden == {"C4"}
    with qtbot.waitSignal(panel.hidden_changed) as blocker:
        panel.checkboxes["C4"].setChecked(True)
    assert blocker.args == [set()]


def test_hidden_choice_survives_channel_off_and_on(panel):
    panel.set_status(make_status())
    panel.checkboxes["C4"].setChecked(False)
    panel.set_status(make_status(enabled=("C1",)))
    assert not panel.checkboxes["C4"].isEnabled()
    assert panel.hidden == {"C4"}
    panel.set_status(make_status(enabled=("C1", "C4")))
    assert panel.checkboxes["C4"].isEnabled()
    assert not panel.checkboxes["C4"].isChecked()
    assert panel.hidden == {"C4"}


def test_pause_button_toggles_text_and_signal(panel, qtbot):
    assert panel.pause_button.text() == "Pause"
    assert not panel.paused
    with qtbot.waitSignal(panel.paused_changed) as blocker:
        panel.pause_button.click()
    assert blocker.args == [True]
    assert panel.paused
    assert panel.pause_button.text() == "Resume"
    with qtbot.waitSignal(panel.paused_changed) as blocker:
        panel.pause_button.click()
    assert blocker.args == [False]
    assert panel.pause_button.text() == "Pause"


def test_clear_resets_to_disconnected_look(panel):
    panel.set_status(make_status())
    panel.checkboxes["C4"].setChecked(False)
    panel.clear()
    assert panel.timebase_label.text() == "—"
    assert panel.trigger_label.text() == "Trigger: —"
    assert panel.state_label.text() == "State: —"
    for name, box in panel.checkboxes.items():
        assert not box.isEnabled()
        assert panel.channel_labels[name].text() == "—"
    assert panel.hidden == {"C4"}


def test_clear_unpauses_and_emits_only_when_paused(panel, qtbot):
    emitted = []
    panel.paused_changed.connect(emitted.append)
    panel.clear()
    assert emitted == []
    panel.pause_button.setChecked(True)
    with qtbot.waitSignal(panel.paused_changed) as blocker:
        panel.clear()
    assert blocker.args == [False]
    assert not panel.paused
    assert panel.pause_button.text() == "Pause"
    assert emitted == [True, False]
