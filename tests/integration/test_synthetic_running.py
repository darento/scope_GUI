"""The synthetic bench as a running scope: trigger modes, ARM/FRTR, on-demand compatibility.

The scope is driven directly (write/read_raw/query) and its clock is replaced by a manual one,
so no test sleeps or depends on timing.
"""

import pytest
from pyvisa.errors import VisaIOError
from synthetic_scope import Scene, SyntheticScope

from scope_gui.wavedesc import decode_waveform, parse_descriptor, split_block

RATE = 20.0
PERIOD = 1 / RATE
CHANNELS = ("C1", "C2", "C3", "C4")


class ManualClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make(**kwargs) -> tuple[SyntheticScope, ManualClock]:
    scope = SyntheticScope(Scene(points=2000), rate_hz=RATE, seed=1, **kwargs)
    clock = ManualClock()
    scope.clock = clock
    scope._origin = clock() - PERIOD  # as if made now
    return scope, clock


def trigger_time(scope: SyntheticScope, channel: str = "C1") -> float:
    """Trigger time of what ``Cn:WF? ALL`` returns now."""
    scope.write(f"{channel}:WF? ALL")
    return decode_waveform(scope.read_raw())[0].trigger_time


def descriptor_time(scope: SyntheticScope, channel: str = "C1") -> float:
    scope.write(f"{channel}:WF? DESC")
    return parse_descriptor(split_block(scope.read_raw())).trigger_time


def mode(scope: SyntheticScope) -> str:
    return scope.query("TRMD?")


@pytest.mark.parametrize("name", ["AUTO", "NORM"])
def test_running_modes_return_the_newest_acquisition(name):
    scope, clock = make(trigger_mode=name)
    assert mode(scope) == f"TRMD {name}"
    first = trigger_time(scope)
    clock.advance(PERIOD * 0.4)  # within one period: still the same trigger
    assert trigger_time(scope, "C3") == first
    assert descriptor_time(scope, "C2") == first
    clock.advance(PERIOD * 1.5)  # more than one period later
    second = trigger_time(scope)
    assert second > first
    assert trigger_time(scope, "C4") == second


def test_skipped_triggers_are_not_generated():
    scope, clock = make()
    first = trigger_time(scope)
    clock.advance(10.0)  # 200 triggers nobody reads
    after = trigger_time(scope)
    assert scope.acquisitions == 2
    assert after - first == pytest.approx(10.0, abs=1e-6)  # the trigger time still advanced


def test_channels_read_one_after_another_can_come_from_different_triggers():
    scope, clock = make()
    stamps = []
    for channel in CHANNELS:
        stamps.append(trigger_time(scope, channel))
        clock.advance(PERIOD * 1.2)  # a transfer takes longer than a period
    assert len(set(stamps)) == len(CHANNELS)


def test_arm_stays_single_until_the_trigger_is_due_then_stops():
    scope, clock = make()
    scope.write("ARM")
    assert mode(scope) == "TRMD SINGLE"
    clock.advance(PERIOD * 0.3)
    assert mode(scope) == "TRMD SINGLE"
    clock.advance(PERIOD)
    assert mode(scope) == "TRMD STOP"
    held = trigger_time(scope)
    # all four channels, read with time passing, share the one trigger time
    stamps = {}
    for channel in CHANNELS:
        clock.advance(PERIOD * 2)
        stamps[channel] = trigger_time(scope, channel)
    assert set(stamps.values()) == {held}
    assert mode(scope) == "TRMD STOP"


def test_arm_while_running_replaces_the_picture_with_a_new_trigger():
    scope, clock = make()
    before = trigger_time(scope)
    scope.write("ARM")
    clock.advance(PERIOD * 1.1)
    assert mode(scope) == "TRMD STOP"
    assert trigger_time(scope) > before


def test_stopped_acquisition_is_a_decodable_block_per_channel():
    scope, clock = make()
    scope.write("ARM")
    clock.advance(PERIOD * 2)
    for channel in CHANNELS:
        scope.write(f"{channel}:WF? ALL")
        desc, volts = decode_waveform(scope.read_raw())
        assert desc.source == channel
        assert volts.size == 2000


def test_without_triggers_only_frtr_completes_an_arm():
    scope, clock = make(triggers=False)
    scope.write("ARM")
    clock.advance(60.0)
    assert mode(scope) == "TRMD SINGLE"
    scope.write("FRTR")
    assert mode(scope) == "TRMD STOP"
    held = trigger_time(scope)
    assert held > 0
    scope.write("ARM")
    clock.advance(60.0)
    assert mode(scope) == "TRMD SINGLE"
    scope.write("FRTR")
    assert mode(scope) == "TRMD STOP"
    assert trigger_time(scope) > held


def test_frtr_completes_an_armed_acquisition_at_once():
    scope, clock = make()
    scope.write("ARM")
    scope.write("FRTR")  # no time has passed: the trigger was not due
    assert mode(scope) == "TRMD STOP"
    assert scope.acquisitions == 1


def test_frtr_while_stopped_changes_nothing():
    scope, clock = make(trigger_mode="STOP")
    held = trigger_time(scope)
    count = scope.acquisitions
    scope.write("FRTR")
    clock.advance(5.0)
    assert mode(scope) == "TRMD STOP"
    assert trigger_time(scope) == held
    assert scope.acquisitions == count


def test_frtr_while_running_does_nothing():
    scope, clock = make(trigger_mode="NORM")
    scope.write("FRTR")
    assert mode(scope) == "TRMD NORM"
    assert scope.acquisitions == 0


def test_stop_holds_whatever_time_passes():
    scope, clock = make()
    scope.write("TRMD STOP")
    assert mode(scope) == "TRMD STOP"
    held = trigger_time(scope)
    clock.advance(30.0)
    assert trigger_time(scope, "C4") == held
    assert scope.acquisitions == 1


def test_trmd_norm_runs_again_after_a_stop():
    scope, clock = make()
    scope.write("TRMD STOP")
    held = trigger_time(scope)
    scope.write("TRMD NORM")
    assert mode(scope) == "TRMD NORM"
    clock.advance(PERIOD * 3)
    assert trigger_time(scope) > held


def test_trmd_single_arms_like_arm():
    scope, clock = make(triggers=False)
    scope.write("TRMD SINGLE")
    assert mode(scope) == "TRMD SINGLE"
    clock.advance(PERIOD * 5)
    assert mode(scope) == "TRMD SINGLE"
    scope.write("FRTR")
    assert mode(scope) == "TRMD STOP"
    scope2, clock2 = make()
    scope2.write("TRMD SINGLE")
    clock2.advance(PERIOD * 1.1)
    assert mode(scope2) == "TRMD STOP"


def test_trigger_times_never_go_backwards():
    scope, clock = make()
    stamps = [trigger_time(scope)]
    for command in ("ARM", "FRTR", "TRMD NORM", "TRMD SINGLE", "FRTR", "TRMD AUTO"):
        scope.write(command)
        clock.advance(PERIOD * 0.3)
        stamps.append(trigger_time(scope))
    assert stamps == sorted(stamps)


def test_control_commands_are_recorded_and_have_no_reply():
    scope, clock = make()
    for command in ("ARM", "FRTR", "TRMD NORM", "TRMD STOP"):
        scope.write(command)
        with pytest.raises(VisaIOError):
            scope.read_raw()  # no reply: times out like the scope
    assert scope.controls == ["ARM", "FRTR", "TRMD NORM", "TRMD STOP"]
    assert scope.sent == scope.controls
    mode(scope)
    trigger_time(scope)
    assert scope.controls == ["ARM", "FRTR", "TRMD NORM", "TRMD STOP"]  # queries are not controls
    assert scope.sent[-2:] == ["TRMD?", "C1:WF? ALL"]


def test_unknown_trigger_mode_is_not_a_control():
    scope, _ = make()
    scope.write("TRMD BOGUS")
    assert scope.controls == []
    assert mode(scope) == "TRMD NORM"


# --- on_demand: the 002 behaviour -----------------------------------------------------------
def test_on_demand_makes_a_new_acquisition_per_descriptor_read():
    scope = SyntheticScope(Scene(points=2000), rate_hz=1000, seed=2, on_demand=True)
    stamps = []
    for expected in (1, 2, 3):
        desc = descriptor_time(scope)
        assert scope.acquisitions == expected
        # the following full reads are of that same acquisition
        assert {trigger_time(scope, ch) for ch in CHANNELS} == {desc}
        assert scope.acquisitions == expected
        stamps.append(desc)
    assert stamps[1] - stamps[0] == pytest.approx(1 / 1000, abs=1e-6)
    assert stamps == sorted(set(stamps))


def test_on_demand_ignores_the_trigger_mode():
    scope = SyntheticScope(Scene(points=2000), rate_hz=1000, seed=2, on_demand=True)
    scope.write("TRMD STOP")
    assert mode(scope) == "TRMD STOP"
    first = descriptor_time(scope)
    assert descriptor_time(scope) > first
    assert scope.controls == ["TRMD STOP"]
