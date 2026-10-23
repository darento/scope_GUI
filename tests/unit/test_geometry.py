import numpy as np
import pytest

from scope_gui.models import (
    Y_RANGE_DIV,
    AcquisitionSettings,
    ChannelSettings,
    TriggerMode,
    div_to_volts,
    volts_to_div,
    x_range,
)

C1 = ChannelSettings("C1", True, 1.0, -3.01, "D1M")


def acq(tdiv, trdl):
    return AcquisitionSettings(tdiv, trdl, TriggerMode.AUTO, "SINGLE")


def test_x_range_matches_horiz_offset_of_fixture():
    # Captured: TDIV 100 ns, TRDL -184 ns, HORIZ_OFFSET -316.087 ns (research R6).
    left, right = x_range(acq(100e-9, -184e-9))
    assert left == pytest.approx(-316e-9)
    assert right == pytest.approx(684e-9)


def test_x_range_research_example():
    left, right = x_range(acq(5e-6, -9.2e-6))
    assert (left, right) == (pytest.approx(-15.8e-6), pytest.approx(34.2e-6))


def test_volts_to_div():
    assert volts_to_div(3.01, C1) == pytest.approx(0.0)  # screen centre is -offset
    assert volts_to_div(4.01, C1) == pytest.approx(1.0)
    assert volts_to_div(np.array([-0.99, 7.01]), C1) == pytest.approx([-4.0, 4.0])


def test_div_to_volts_inverse():
    for div in (-4, -1.5, 0, 2.25, 4):
        assert volts_to_div(div_to_volts(div, C1), C1) == pytest.approx(div)


def test_y_range():
    assert Y_RANGE_DIV == (-4, 4)
