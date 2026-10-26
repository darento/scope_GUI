"""Persistence density map (research R7): rasterising, fading, colouring. Pure numpy."""

import time

import numpy as np
import pytest

from scope_gui.models import (
    CHANNEL_COLORS,
    AcqState,
    AcquisitionSettings,
    ChannelSettings,
    ScopeStatus,
    TriggerMode,
    Waveform,
)
from scope_gui.ui.persistence import Persistence

W, H = 100, 40  # 1 unit of time per column, 1 division per row


def make(depth=None) -> Persistence:
    p = Persistence(W, H, depth)
    p.set_view((0.0, 100.0), (0.0, 40.0))
    return p


def hits(p: Persistence, channel="C1") -> np.ndarray:
    """Boolean (H, W) map of the pixels of one channel's layer."""
    return p.density(channel) > 0


def spans(mask: np.ndarray) -> list[tuple[int, int] | None]:
    """(lowest, highest) lit row of each column, None for an empty column."""
    out = []
    for column in mask.T:
        rows = np.flatnonzero(column)
        out.append((int(rows[0]), int(rows[-1])) if rows.size else None)
    return out


def is_contiguous(mask: np.ndarray) -> bool:
    return all(s is None or mask[s[0] : s[1] + 1, j].all() for j, s in enumerate(spans(mask)))


def connected(mask: np.ndarray) -> bool:
    """Every column is lit and neighbouring columns touch (no gap in the line)."""
    s = spans(mask)
    if any(x is None for x in s):
        return False
    return all(a[0] <= b[1] + 1 and b[0] <= a[1] + 1 for a, b in zip(s, s[1:], strict=False))


# --- rasterising ---------------------------------------------------------------------------
def test_a_flat_trace_lights_one_pixel_per_column():
    p = make()
    t = np.linspace(0, 100, 1001)
    p.add({"C1": (t, np.full(t.size, 10.5))})
    mask = hits(p)
    assert mask.sum() == W
    assert (np.flatnonzero(mask.any(axis=1)) == [10]).all()


def test_each_column_gets_every_pixel_between_the_min_and_max_of_its_samples():
    p = make()
    t = np.linspace(0.05, 99.95, 2000)  # 20 samples per column
    y = np.where(np.arange(t.size) % 2 == 0, 5.2, 12.7)
    p.add({"C1": (t, y)})
    mask = hits(p)
    assert spans(mask) == [(5, 12)] * W
    assert mask.sum() == 8 * W  # each pixel once, nothing else


def test_columns_follow_their_own_samples():
    p = make()
    t = np.linspace(0.05, 99.95, 2000)
    column = (t // 1).astype(int)
    y = np.where(np.arange(t.size) % 2 == 0, 5.5, 5.5 + (column % 10))  # amplitude varies
    p.add({"C1": (t, y)})
    s = spans(hits(p))
    for j in range(5, W - 5):
        assert s[j][0] <= 5  # the low samples
        assert s[j][1] >= 5 + (j % 10) - 1  # the high samples (neighbours may extend it)
    assert is_contiguous(hits(p))


def test_a_fast_edge_with_fewer_samples_than_columns_has_no_gaps():
    p = make()
    p.add({"C1": (np.array([0.0, 49.0, 51.0, 100.0]), np.array([5.0, 5.0, 30.0, 30.0]))})
    mask = hits(p)
    assert connected(mask)
    s = spans(mask)
    assert s[10] == (5, 5) and s[90] == (30, 30)
    assert s[49][0] == 5 and s[50][1] == 30  # the edge fills the columns it crosses
    assert s[49][1] >= 16 and s[50][0] <= 17  # ... and they meet in the middle


def test_a_record_with_fewer_samples_than_columns_is_interpolated():
    p = make()
    t = np.array([0.0, 25.0, 50.0, 75.0, 100.0])
    p.add({"C1": (t, np.array([2.0, 30.0, 2.0, 30.0, 2.0]))})
    mask = hits(p)
    assert connected(mask)
    assert mask[16, 12]  # y(12.5) = 16
    assert mask[16, 37]  # y(37.5) = 16 on the way down
    assert mask[2, 0] and mask[30, 25]
    assert not mask[35].any()  # never above the samples


def test_a_trace_that_leaves_the_view_is_clipped_to_its_edge_rows():
    p = make()
    t = np.linspace(0, 100, 101)
    p.add({"C1": (t, np.linspace(-20, 80, 101))})  # crosses the whole view diagonally
    mask = hits(p)
    s = spans(mask)
    assert s[0] is None or s[0][1] <= 1  # starts below the view
    assert any(x is not None and x[1] == H - 1 for x in s)
    assert any(x is not None and x[0] == 0 for x in s)
    assert mask[20, 40]  # y = 20 at t = 40


def test_samples_outside_the_view_add_nothing():
    p = make()
    t = np.linspace(0, 100, 101)
    p.add({"C1": (t, np.full(101, 100.0))})  # above the view
    assert p.density("C1") is None or not hits(p).any()
    p = make()
    p.add({"C1": (t + 500.0, np.full(101, 10.0))})  # later than the view
    assert p.density("C1") is None or not hits(p).any()
    assert not p.image().any()


def test_a_record_covering_only_part_of_the_view_lights_only_those_columns():
    p = make()
    t = np.linspace(20.0, 60.0, 401)
    p.add({"C1": (t, np.full(t.size, 10.5))})
    columns = np.flatnonzero(hits(p).any(axis=0))
    assert columns.min() == 20 and columns.max() == 60  # the last sample is at t = 60
    assert columns.size == 41


def test_evenly_spaced_samples_can_be_given_as_t0_and_dt():
    n = 4001
    t = 0.0 + np.arange(n) * 0.025
    y = 20 + 10 * np.sin(t / 7.0)
    a, b = make(), make()
    a.add({"C1": (t, y)})
    b.add({"C1": ((0.0, 0.025), y)})
    assert np.array_equal(hits(a), hits(b))


def test_waveforms_are_converted_per_channel_from_volts():
    status = ScopeStatus(
        tuple(ChannelSettings(n, True, 0.5, 10.0, "D50") for n in ("C1", "C2")),
        AcquisitionSettings(10.0, -50.0, TriggerMode.NORM, "SINGLE"),
        AcqState.ACQUIRING,
        0.0,
    )
    t = np.arange(1001) * 0.1
    volts = (np.sin(t / 5) * 4.0).astype(np.float32)
    wave = Waveform("C1", volts, 0.0, 0.1, 0.0, 0.0)
    from_volts, from_divisions = make(), make()
    from_volts.add_waveforms({"C1": wave, "C4": wave}, status)  # C4 is not in the status
    from_divisions.add(
        {"C1": (t, (volts.astype(np.float64) + 10.0) / 0.5)}
    )  # div = (V + ofs) / V/div
    assert from_volts.density("C4") is None
    assert from_volts.density("C1") is not None
    differing = np.logical_xor(hits(from_volts), hits(from_divisions)).sum()
    assert differing <= 0.02 * hits(from_divisions).sum()  # float32 rounding at pixel borders


# --- fading -----------------------------------------------------------------------------------
@pytest.mark.parametrize("depth", [10, 100, 1000])
def test_density_fades_by_one_minus_one_over_n_per_acquisition(depth):
    p = make(depth)
    p.add({"C1": (np.array([0.0, 100.0]), np.array([10.5, 10.5]))})
    assert p.density("C1")[10, 50] == pytest.approx(1.0)
    for k in range(1, 6):
        p.add({})  # an acquisition without this trace
        assert p.density("C1")[10, 50] == pytest.approx((1 - 1 / depth) ** k, rel=1e-5)
    p.add({"C1": (np.array([0.0, 100.0]), np.array([10.5, 10.5]))})
    assert p.density("C1")[10, 50] == pytest.approx((1 - 1 / depth) ** 6 + 1, rel=1e-5)


def test_infinite_persistence_never_fades():
    p = make(None)
    p.add({"C1": (np.array([0.0, 100.0]), np.array([10.5, 10.5]))})
    for _ in range(50):
        p.add({})
    assert p.density("C1")[10, 50] == pytest.approx(1.0)
    assert p.count == 51


def test_depth_can_change_without_losing_the_picture():
    p = make(100)
    p.add({"C1": (np.array([0.0, 100.0]), np.array([10.5, 10.5]))})
    p.set_depth(10)
    assert p.depth == 10 and p.count == 1 and hits(p).any()
    p.add({})
    assert p.density("C1")[10, 50] == pytest.approx(0.9)
    with pytest.raises(ValueError):
        p.set_depth(0)


def test_reset_empties_the_map():
    p = make(100)
    p.add({"C1": (np.array([0.0, 100.0]), np.array([10.5, 10.5]))})
    assert p.image().any()
    p.reset()
    assert p.count == 0 and p.density("C1") is None
    assert not p.image().any()


def test_view_or_size_change_restarts_but_the_same_view_does_not():
    p = make(100)
    flat = {"C1": (np.array([0.0, 100.0]), np.array([10.5, 10.5]))}
    p.add(flat)
    p.set_view((0.0, 100.0), (0.0, 40.0))
    assert p.count == 1
    p.set_view((0.0, 50.0), (0.0, 40.0))  # zoomed
    assert p.count == 0 and p.view == ((0.0, 50.0), (0.0, 40.0))
    p.add(flat)
    p.set_view((0.0, 50.0), (-4.0, 4.0))  # V/div changed
    assert p.count == 0
    p.add(flat)
    p.set_size(W, H)
    assert p.count == 1
    p.set_size(W * 2, H)
    assert p.count == 0 and p.image().shape == (H, W * 2, 4)
    with pytest.raises(ValueError):
        p.set_view((1.0, 1.0), (0.0, 1.0))


def test_adding_before_a_view_is_an_error():
    with pytest.raises(RuntimeError):
        Persistence(10, 10).add({})


# --- colours ------------------------------------------------------------------------------------
def rgb_of(name: str) -> np.ndarray:
    return np.array([int(CHANNEL_COLORS[name][i : i + 2], 16) for i in (1, 3, 5)])


def test_a_pixel_hit_every_time_has_the_full_channel_colour():
    p = make(10)
    for _ in range(40):
        p.add({"C2": (np.array([0.0, 100.0]), np.array([10.5, 10.5]))})
    image = p.image()
    assert image.shape == (H, W, 4) and image.dtype == np.uint8
    np.testing.assert_allclose(image[10, 50, :3], rgb_of("C2"), atol=1)
    assert image[10, 50, 3] == 255


def test_colour_is_scaled_by_the_square_root_of_the_density():
    p = make(None)
    for i in range(16):
        row = 10.5 if i < 4 else 20.5  # one pixel hit 4 times in 16, the other 12 times
        p.add({"C3": (np.array([0.0, 100.0]), np.array([row, row]))})
    image = p.image()
    np.testing.assert_allclose(image[10, 50, :3], rgb_of("C3") * np.sqrt(4 / 16), atol=1)
    np.testing.assert_allclose(image[20, 50, :3], rgb_of("C3") * np.sqrt(12 / 16), atol=1)


def test_untouched_pixels_are_transparent_black():
    p = make(None)
    p.add({"C1": (np.array([0.0, 100.0]), np.array([10.5, 10.5]))})
    image = p.image()
    assert (image[30] == 0).all()
    assert image[10, :, 3].min() == 255


def test_each_channel_uses_its_own_colour_and_overlaps_add_up():
    p = make(None)
    for _ in range(4):
        p.add(
            {
                "C1": (np.array([0.0, 100.0]), np.array([10.5, 10.5])),
                "C4": (np.array([0.0, 100.0]), np.array([20.5, 20.5])),
                "C2": (np.array([0.0, 100.0]), np.array([30.5, 30.5])),
                "C3": (np.array([0.0, 100.0]), np.array([30.5, 30.5])),
            }
        )
    image = p.image()
    np.testing.assert_allclose(image[10, 5, :3], rgb_of("C1"), atol=1)
    np.testing.assert_allclose(image[20, 5, :3], rgb_of("C4"), atol=1)
    np.testing.assert_allclose(
        image[30, 5, :3], np.minimum(rgb_of("C2") + rgb_of("C3"), 255), atol=1
    )


def test_channels_outside_the_view_add_nothing_to_the_image():
    p = make(None)
    p.add({"C1": (np.array([0.0, 100.0]), np.array([10.5, 10.5]))})
    p.add({"C2": (np.array([0.0, 100.0]), np.array([-30.0, -30.0]))})  # below the view
    image = p.image()
    assert p.density("C2") is None
    assert set(np.flatnonzero(image[..., 3].any(axis=1))) == {10}  # only C1's row is lit


# --- cost ---------------------------------------------------------------------------------------
def test_four_channels_of_100k_points_are_added_and_drawn_quickly():
    p = Persistence(1000, 400, 100)
    p.set_view((-1e-7, 4e-7), (-4.0, 4.0))
    n = 100_000
    t = (-1e-7, 5e-7 / n)
    rng = np.random.default_rng(0)
    traces = {
        name: (t, rng.normal(0, 0.3, n).astype(np.float32) + i - 1.5)
        for i, name in enumerate(("C1", "C2", "C3", "C4"))
    }
    p.add(traces)
    start = time.perf_counter()
    for _ in range(5):
        p.add(traces)
        p.image()
    per_acquisition = (time.perf_counter() - start) / 5
    assert per_acquisition < 0.1, f"{per_acquisition * 1000:.0f} ms"
