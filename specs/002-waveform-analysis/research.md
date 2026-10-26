# Research: Waveform Analysis

**Feature**: 002-waveform-analysis | **Date**: 2026-10-26

Findings marked *(measured)* come from a prototype of the analysis code run on the synthetic
bench (default scene unless stated, 2,000 acquisitions, seeds fixed) on the development PC
(Windows 11, Python 3.13, numpy 2.5, pyqtgraph 0.14, offscreen Qt for render timings). The
prototype is a spike: implementation starts from this design, not from its code.

## R1. Where the analysis runs

*(measured)* `measure_all` for 10 measurements on 4 channels:

| Record length | Time per acquisition |
|---------------|----------------------|
| 10k points | 1.3 ms |
| 100k points | 7.3 ms |
| 500k points | 57 ms |

- **Decision**: Run measurements on the GUI thread, in the `waveforms_updated` slot, before
  drawing. Skip them while paused (FR-023).
- **Rationale**: Real update rates are scope-bound (≤ 5/s at 100k × 4, ~1.5/s at 500k × 3,
  feature 001 R2). 7 ms per update is < 4 % of the GUI's time at 5/s; 57 ms at 1.5/s is < 9 %
  and far below the 0.2 s responsiveness limit. Waveforms already arrive on the GUI thread, so
  no copying or extra synchronisation is needed.
- **Alternatives**: In the worker thread: every millisecond delays the next transfer and so
  lowers the update rate (against SC-005), and measurement definitions would have to cross
  threads. A separate analysis thread: extra thread, queueing and stale-result handling for no
  benefit at these rates (Principle V).

## R2. Base, top and noise (reference levels)

*(measured)* Problems found with a naïve estimate and their fixes:

| Problem | Effect | Fix |
|---------|--------|-----|
| Base from the gated samples only | Gate 25–60 ns around a SiPM pulse: the window is mostly pulse, base wrong, CFD Δt unusable | Base and noise always from the whole record; for pulses the top is the peak inside the gate |
| Noise as standard deviation of base samples | The pulse tail among the "base" samples inflated it; 59 % of real pulses rejected | Noise = 1.4826 × median absolute deviation (robust; equals the rms for Gaussian noise) |

- **Decision**: Split the record's samples at the mid-level `(min + max) / 2`.
  - Fewer than 20 % above → positive pulses: base = median of the lower samples, top = maximum
    (inside the gate).
  - More than 80 % above → negative pulses: base = median of the upper samples, top = minimum
    (inside the gate).
  - Otherwise square-like: base and top = medians of the lower and upper samples.
  - Noise = robust rms of the base samples.
  - Amplitude = top − base (negative for negative pulses).
- **Rationale**: One rule covers the lab's two signal families. Square-like signals get the
  usual "base/top" levels, so 10–90 % refers to the flat levels, not overshoot. Pulses get
  baseline/peak, so constant fraction and amplitude mean what physicists expect. Polarity is
  detected, so the same measurement works on positive and negative SiPM readouts.
- **Known bias**: the peak of a noisy pulse is its highest sample, so amplitudes are ~2 noise
  rms high. *(measured)* Photoelectron peaks at 22.1/41.3/61.2/81.1 mV for 20 mV per
  photoelectron: constant offset, correct spacing (19.7 mV). Documented, not corrected
  (scopes behave the same).
- **Alternatives**: Histogram-mode top/base like a scope's "top"/"base": under-estimates the
  peak of narrow pulses. Fixed pre-trigger baseline window: needs another setting and fails
  for free-running square signals.

## R3. Noise-only acquisitions

*(measured)* About 5 % of acquisitions have no photoelectron (Poisson mean 3). A 20 %
constant-fraction level on pure noise gave Δt values anywhere in the record: σ = 65 ns
instead of ~0.13 ns.

- **Decision**: Amplitude-relative quantities (percentage levels, rise/fall, width, period,
  duty cycle) are missed when |top − base| < 5 × noise rms (FR-007a). Volt-level crossings,
  amplitude, area, extremes and mean are still measured (the 0-photoelectron pedestal belongs
  in the amplitude spectrum).
- **Rationale**: For Gaussian noise the extreme of 10⁵ samples is ~4.4 σ from the median, so
  5 σ rejects noise-only records while 1 photoelectron (20 mV over 1.2 mV noise, ~17 σ)
  passes.

## R4. Threshold crossings

- **Decision**:
  - Vectorised state scan: a level is armed when the signal is beyond it by the hysteresis,
    and fires on the first sample past the level.
  - Hysteresis = max(5 % of |amplitude|, 3 × noise rms).
  - Time interpolated linearly between the two samples.
  - Δt and Time @ level use the **first** crossing in the record or gate.
  - Rise time uses the first *complete* edge (a 90 % crossing with a 10 % crossing before it).
- *(measured)* Without the noise term, a 10 mV level on a SiPM tail with band-limited noise
  counted extra edges. Rise time of the clock was missed in 49 % of acquisitions because the
  first edge was cut by the start of the record; with the first-complete-edge rule it is
  1.001 ns ± 28 ps for a true 1.0 ns.
- **Rationale**: Linear interpolation gives sub-sample timing (SC-003). The noise-scaled
  hysteresis stops noise re-triggering without hiding real pulses. "First crossing" matches the
  user's request and keeps the definitions simple; per-pulse analysis is out of scope.
- **Alternatives**: Sinc or cubic interpolation: marginal gain at 8-bit resolution, more code.
  Per-pulse lists: later feature.

## R5. Gaussian fit without new dependencies

- **Decision**: Fit a parabola to ln(counts), weighted by √counts, over ±2 σ of the current
  estimate. Start from the highest bin with σ from its half-maximum width, and iterate 4 times.
  No fit (shown as such) if the peak has < 3 non-empty bins, the parabola opens upwards, or
  there are < 10 entries.
- *(measured)* 20-photoelectron scene: fitted mean 1998.8 ps, σ 117.5 ps vs true 2000 ps,
  114 ps → SC-002 met. Default scene: the first version started from the overall spread and
  fitted across several photoelectron peaks (σ = 50 mV); starting from the half-max width
  follows a single peak.
- **Rationale**: Standard log-parabola (Caruana) estimate, a few lines of numpy, robust on the
  sparse histograms of a live run.
- **Alternatives**: scipy `curve_fit`: new 40 MB dependency for one fit (Principle V);
  plain mean/σ of all values: pulled by tails (65 ns vs 0.13 ns in R3).

## R6. Histogram range

*(measured)* Default scene: 27 % of constant-fraction Δt values are dark-count outliers
(first crossing on a dark count before the pulse, ±100 ns). With a min–max range the
0.13 ns peak falls into one bin and cannot be fitted.

- **Decision**: Three range modes:
  - **Auto (robust)**, the default: median ± 8 × robust σ (MAD-based), falling back to min–max
    when the MAD is 0. The number of values outside the range is shown.
  - **Full**: min–max.
  - **Manual**: from/to entered by the user.
- *(measured)* Robust range: fit 1996 ps / 129 ps with 509 values outside. With a 25–60 ns
  gate: 45 outside, fit 1997 ps / 128 ps. This is how the gate earns its place.
- **Alternatives**: Percentile range (0.5–99.5 %): still spans the outliers when they are 27 %.

## R7. Persistence display

*(measured, 4 channels × 100k points)*

| Approach | Time per update |
|----------|-----------------|
| 20 overlaid curves per channel | 2,279 ms |
| Density image: binning + colouring | 34 ms |
| Plain 4 curves (reference) | 23 ms |

- **Decision**: A density map over the current view (≈ 1 px per bin). On each acquisition:
  - existing density × (1 − 1/N), or no fading for infinite;
  - add each channel's samples, binned into its own layer;
  - colour each layer with the channel colour at √density, sum into one RGB image, and show
    it behind the traces.
- Reset on any view or scale change, since the bins would no longer match.
- **Rationale**: Mirrors the scope's analog persistence; cost independent of depth; makes
  photoelectron bands and edge jitter visible.
- **Alternatives**: Exact "last N" (ring of N sparse histograms): more code for no visible
  difference. Overlaid curves: too slow (above).

## R8. Zoom and pan

- **Decision**: pyqtgraph `ViewBox`:
  - mouse enabled, `RectMode` (left-drag = box zoom), wheel zoom, middle-drag pan;
  - `sigRangeChangedManually` marks the view as zoomed, after which `set_status` stops
    setting the range (the grid still follows the scope);
  - "Reset view" button and double-click restore the scope screen and clear the flag;
  - context menu stays disabled (its options would conflict with the scope mirror).
- **Rationale**: Built in, no extra code for the gestures; one flag decides who owns the range.

## R9. Cursors, gate and level lines

- **Decision**:
  - **Cursors**: two movable vertical `InfiniteLine`s, labelled 1 and 2, placed at 1/3 and 2/3
    of the current view when switched on.
  - **Readout**: Δt and 1/Δt, plus each visible channel's voltage at each cursor, linearly
    interpolated from the waveform samples. It is refreshed on drag and on each acquisition.
  - **Gate**: a non-movable shaded `LinearRegionItem` that follows the cursors. Choosing
    "between cursors" switches the cursors on.
  - **Level lines**: horizontal dashed `InfiniteLine`s in the channel colour, one per volt
    level of the selected measurement, placed in divisions with that channel's scale.
    - While dragging, the stored volts follow the line, so a scale update does not snap it
      back.
    - On release, the measurement is updated and its statistics are cleared.
- **Rationale**: Built-in items; voltages from samples are exact rather than the hover's
  div→V mapping.

## R10. Statistics storage and export alignment

- **Decision**:
  - **Storage**: one numpy float64 ring buffer of 100,000 values per measurement, with NaN
    for missed values. Every processed acquisition adds exactly one entry to every
    measurement and to a parallel ring of trigger times, so all histories end at the same
    acquisition.
  - **Export**: write the last *k* rows aligned at the end. A newer measurement's column is
    empty before it existed (US5-2).
  - **Summary**: computed with numpy from the finite values on each update.
- *(measured)* Summary of 100k values ≈ 0.2 ms; 10 measurements ≈ 2 ms per update. Memory
  0.8 MB per measurement.
- **Alternatives**: Running sums (Welford): no histogram, and statistics would differ from the
  histogram after 100k. Python lists: slower, no vector maths.

## R11. CSV export off the GUI thread

- **Decision**: On the GUI thread, copy the histories (a few MB) and take the file name from
  `QFileDialog`. Write the CSV in a `QThreadPool` task. Report done or failed back through a
  queued signal, shown in the status bar.
  - Columns: `trigger_time_s`, then one per measurement with the unit in the header, e.g.
    `Δt C2 lead 20% → C3 lead 20% [s]`.
  - UTF-8 with BOM, so Excel shows Δ and µ.
- **Rationale**: Principle II forbids large file writes on the GUI thread; 100k × 10 values
  is ~10 MB of text.

## R12. Remembering measurement definitions

- **Decision**: Store the list as JSON in `QSettings` under `analysis/measurements`
  (`MeasurementSpec.to_dict`). Unknown or invalid entries are skipped and logged when
  loading.
- **Rationale**: Same mechanism as the last address (feature 001 R9); no new storage.

## R13. Synthetic bench

- **Decision**:
  - **`tests/synthetic_scope.py`**: a `Scene` dataclass of signal parameters,
    `SyntheticAcquisition` (one trigger's volts plus its true values) and `SyntheticScope`, a
    VISA-resource stand-in like `FakeVisaResource`.
    - It answers the allowlisted queries with the scene's settings.
    - It makes a new acquisition on each `Cn:WF? DESC`, paced to `rate_hz` by sleeping in the
      worker thread, which stands in for transfer time.
    - It serves `WF? ALL` blocks built with the existing `build_wavedesc`: 8-bit codes at
      25 codes/div, clipped at ±127 like the scope.
  - **`tests/bench.py`**: the launcher, `uv run python tests/bench.py [--rate 20]
    [--points 10000] [--seed N]`.
    - It opens `MainWindow` with a driver that uses the synthetic resource, and disables the
      TCP pre-check in its own process only.
    - It uses a separate settings file, so the bench never changes the real last address or
      measurement list.
    - Window title: "Scope GUI — SYNTHETIC test bench"; identity serial `SYNTHETIC`.
    - On first start it adds a demo set of measurements.
  - **Signals**: as in the spec. Noise is band-limited to 1 GHz (Gaussian filter), because
    white noise at 20 GS/s is unrealistic and exaggerated edge re-triggering (R4).
- **Rationale**: Constitution I/IV. The fake sits behind the real `ScopeDriver`, so allowlist,
  reply validation, decoding and the worker loop are exercised exactly as with the scope, and
  nothing synthetic is importable from `src/`.
- **Alternatives**:
  - A simulated mode inside the app: forbidden (Constitution I, spec 001 FR-009).
  - Feeding `Waveform` objects straight into the GUI: skips the driver and worker, so less
    realistic.

## R14. Settings changed during a run (FR-022)

- **Decision**: The main window compares each new `ScopeStatus` with the previous one. It
  compares channel settings and timebase/trigger delay/trigger mode, and ignores `acq_state`
  and `read_at`. If they differ while statistics hold values, the measurements panel shows
  "Scope settings changed during this run" until Clear.

## R15. Dependencies

- **Decision**: No new dependencies. numpy and pyqtgraph (already used) cover the
  measurements, fit, histograms (`np.histogram`), images (`ImageItem`), scatter
  (`ScatterPlotItem`) and docks (Qt `QDockWidget`). The correlation scatter shows at most the
  latest 5,000 points to stay fast.
