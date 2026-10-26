"""Analog-style persistence: a fading density image of the recent traces (research R7).

Pure numpy, no Qt. For every acquisition each channel's trace is rasterised into the pixel grid
of the current view and added to that channel's density map, which first fades by (1 - 1/N)
(N = depth in acquisitions, ``None`` = never fades). ``image()`` colours every channel with its
scope colour at the square root of its density and sums them.

Image layout (to show it in a pyqtgraph ``ImageItem``): ``(height, width, 4)`` uint8 RGBA, rows
increasing with y (row 0 is ``y_range[0]``, the *bottom*), columns increasing with x. Use
``axisOrder='row-major'`` and ``setRect(x0, y0, x1 - x0, y1 - y0)``. Pixels no trace touched are
transparent; every other pixel is opaque.

A trace is rasterised like the line the plot draws (a polyline through the samples): each pixel
column gets one hit on every pixel between the lowest and highest point of the line inside the
column, whether that comes from several samples in the column (``minimum.reduceat`` over the
samples of each column, no per-sample column arithmetic) or from the line entering and leaving a
column between two distant samples, so a fast edge is a connected run of pixels, not dots.
"""

import numpy as np

from ..models import CHANNEL_COLORS, ScopeStatus, Waveform

DEFAULT_SIZE = (1000, 400)

_COLORS = {
    name: np.array([int(hex_[i : i + 2], 16) for i in (1, 3, 5)], np.float32)
    for name, hex_ in CHANNEL_COLORS.items()
}


class Persistence:
    def __init__(self, width: int = DEFAULT_SIZE[0], height: int = DEFAULT_SIZE[1], depth=100):
        self._width, self._height = int(width), int(height)
        self._depth = depth
        self._view: tuple[tuple[float, float], tuple[float, float]] | None = None
        self._layers: dict[str, np.ndarray] = {}
        self._edges: np.ndarray | None = None
        self._rows = np.arange(self._height)[:, None]
        self.count = 0  # acquisitions added since the last reset

    # --- configuration -----------------------------------------------------------------
    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def depth(self) -> int | None:
        """Fade length in acquisitions; None = infinite."""
        return self._depth

    @property
    def view(self):
        """((x0, x1), (y0, y1)) the map is rasterised for, or None before ``set_view``."""
        return self._view

    def set_size(self, width: int, height: int) -> None:
        """Pixel grid size; the map restarts if it changed."""
        width, height = int(width), int(height)
        if (width, height) != (self._width, self._height):
            self._width, self._height = width, height
            self._rows = np.arange(height)[:, None]
            self._edges = None
            self.reset()

    def set_view(self, x_range: tuple[float, float], y_range: tuple[float, float]) -> None:
        """x range in seconds, y range in divisions; the map restarts if the view changed."""
        view = ((float(x_range[0]), float(x_range[1])), (float(y_range[0]), float(y_range[1])))
        if not (view[0][1] > view[0][0] and view[1][1] > view[1][0]):
            raise ValueError(f"empty view {view}")
        if view != self._view:
            self._view = view
            self._edges = None
            self.reset()

    def set_depth(self, depth: int | None) -> None:
        """Fade over ``depth`` acquisitions (>= 1); None = infinite. Keeps what was drawn."""
        if depth is not None and depth < 1:
            raise ValueError("depth must be at least 1")
        self._depth = depth

    def reset(self) -> None:
        self._layers.clear()
        self.count = 0

    def density(self, channel: str) -> np.ndarray | None:
        """Copy of a channel's faded hit count per pixel, ``(height, width)``; None if empty."""
        layer = self._layers.get(channel)
        return None if layer is None else layer.copy()

    # --- adding traces --------------------------------------------------------------------
    def add(self, traces: dict[str, tuple]) -> None:
        """One acquisition: ``{channel: (times, divisions)}``.

        ``times`` is ascending seconds, either an array or a ``(t0, dt)`` pair for evenly
        spaced samples (no array needed); ``divisions`` is the trace in screen divisions.
        """
        self._begin()
        for name, (times, div) in traces.items():
            self._add_layer(name, times, div, 1.0, 0.0)

    def add_waveforms(self, waveforms: dict[str, Waveform], status: ScopeStatus) -> None:
        """One acquisition straight from the received waveforms (volts converted per channel).

        Cheaper than converting whole records to divisions yourself: only the minimum and
        maximum of each pixel column are converted. Channels the status does not list are
        skipped.
        """
        self._begin()
        names = {ch.name for ch in status.channels}
        for name, wave in waveforms.items():
            if name not in names:
                continue
            ch = status.channel(name)
            self._add_layer(
                name,
                (wave.t0, wave.dt),
                wave.volts,
                1.0 / ch.volts_per_div,
                ch.offset / ch.volts_per_div,
            )

    def _begin(self) -> None:
        if self._view is None:
            raise RuntimeError("set_view() first")
        if self._depth is not None:
            keep = 1.0 - 1.0 / self._depth
            for layer in self._layers.values():
                layer *= keep
        self.count += 1

    def _add_layer(self, name: str, times, y: np.ndarray, scale: float, shift: float) -> None:
        mask = self._hits(times, y, scale, shift)
        if mask is None:
            return
        layer = self._layers.get(name)
        if layer is None:
            layer = self._layers[name] = np.zeros((self._height, self._width), np.float32)
        layer += mask

    # --- rasterising ---------------------------------------------------------------------
    def _column_edges(self) -> np.ndarray:
        if self._edges is None:
            x0, x1 = self._view[0]
            self._edges = x0 + np.arange(self._width + 1) * ((x1 - x0) / self._width)
        return self._edges

    def _hits(self, times, y: np.ndarray, scale: float, shift: float) -> np.ndarray | None:
        """Boolean (height, width) map of the pixels the trace's polyline passes through."""
        n = y.size
        if n < 2:
            return None
        edges = self._column_edges()
        if isinstance(times, tuple):
            t0, dt = times

            def at(k):
                return t0 + k * dt

            idx = np.clip(np.ceil((edges - t0) / dt), 0, n).astype(np.int64)
        else:
            times = np.asarray(times)

            def at(k):
                return times[k]

            idx = np.searchsorted(times, edges, side="left")

        # The polyline at every column boundary: covers columns with no sample of their own.
        k1 = np.clip(idx, 1, n - 1)
        k0 = k1 - 1
        t_lo, t_hi = at(k0), at(k1)
        span = np.where(t_hi > t_lo, t_hi - t_lo, 1.0)
        y0, y1 = y[k0].astype(np.float64), y[k1].astype(np.float64)
        boundary = y0 + (y1 - y0) * np.clip((edges - t_lo) / span, 0.0, 1.0)
        # A boundary at the very start (end) of the record belongs to the column on its right
        # (left) only; the column beyond the record gets nothing from it.
        first_t, last_t = at(0), at(n - 1)
        as_left = (edges >= first_t) & (edges < last_t)
        as_right = (edges > first_t) & (edges <= last_t)
        lo = np.minimum(
            np.where(as_left, boundary, np.inf)[:-1], np.where(as_right, boundary, np.inf)[1:]
        )
        hi = np.maximum(
            np.where(as_left, boundary, -np.inf)[:-1], np.where(as_right, boundary, -np.inf)[1:]
        )

        # The samples inside each column.
        first, last = int(idx[0]), int(idx[-1])
        counts = np.diff(idx)
        occupied = counts > 0
        if last > first and occupied.any():
            starts = idx[:-1][occupied] - first
            view = y[first:last]
            lo[occupied] = np.minimum(lo[occupied], np.minimum.reduceat(view, starts))
            hi[occupied] = np.maximum(hi[occupied], np.maximum.reduceat(view, starts))

        (_, _), (v0, v1) = self._view
        gain = self._height / (v1 - v0)
        with np.errstate(invalid="ignore"):
            row_lo = np.floor((lo * scale + shift - v0) * gain)
            row_hi = np.floor((hi * scale + shift - v0) * gain)
        ok = (
            np.isfinite(row_lo) & np.isfinite(row_hi) & (row_hi >= 0) & (row_lo <= self._height - 1)
        )
        if not ok.any():
            return None
        row_lo = np.where(ok, np.clip(row_lo, 0, self._height - 1), self._height)
        row_hi = np.where(ok, np.clip(row_hi, 0, self._height - 1), -1)
        return (self._rows >= row_lo) & (self._rows <= row_hi)

    # --- display ---------------------------------------------------------------------------
    def image(self) -> np.ndarray:
        """RGBA ``(height, width, 4)`` uint8; see the module docstring for the layout."""
        rgba = np.zeros((self._height, self._width, 4), np.uint8)
        if not self._layers or self.count == 0:
            return rgba
        if self._depth is None:
            reference = float(self.count)  # a pixel hit every time reads 1.0
        else:
            keep = 1.0 - 1.0 / self._depth
            reference = float(self.count) if keep == 1.0 else (1 - keep**self.count) / (1 - keep)
        names = list(self._layers)
        pixels = self._height * self._width
        intensity = np.empty((len(names), pixels), np.float32)
        for row, name in zip(intensity, names, strict=True):
            np.multiply(self._layers[name].reshape(-1), np.float32(1.0 / reference), out=row)
            np.minimum(row, 1.0, out=row)
            np.sqrt(row, out=row)
        colors = np.stack([_COLORS[name] for name in names], axis=1)  # (3, layers)
        rgb = colors @ intensity  # (3, pixels): every layer in its colour, summed
        np.minimum(rgb, 255.0, out=rgb)
        np.rint(rgb, out=rgb)
        shape = (self._height, self._width)
        for k in range(3):
            rgba[:, :, k] = rgb[k].reshape(shape)
        rgba[:, :, 3] = np.where(rgb.any(axis=0), 255, 0).reshape(shape)
        return rgba
