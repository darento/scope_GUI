---

description: "Task list for 002-waveform-analysis"
---

# Tasks: Waveform Analysis

**Input**: Design documents from `/specs/002-waveform-analysis/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/analysis.md,
contracts/ui.md, contracts/synthetic-bench.md, quickstart.md

**Tests**: Included — required by Constitution Principle IV (every feature ships pytest tests that
run without hardware; hardware tests marked `@pytest.mark.hardware`) and listed in plan.md.

**Organization**: Tasks are grouped by user story (US1 Synthetic bench, US2 Measurements and
statistics, US3 Distributions, US4 Waveform inspection, US5 Export).

**Prototype**: `src/scope_gui/analysis.py` and `tests/synthetic_scope.py` exist uncommitted from
the planning research. They are a starting point, not the design: each task below that touches
them reworks them to match the contracts and the task's tests.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Single project: `src/scope_gui/`, `tests/` at repository root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the baseline; no new dependencies (research R15)

- [X] T001 Run `uv run pytest` (expect the 199 tests of feature 001 to pass) and
  `uv run ruff check` / `uv run ruff format --check` on the branch before any change, so later
  failures are attributable; do not add dependencies to `pyproject.toml` (R15)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The measurement vocabulary (`Edge`, `Kind`, `Level`, `MeasurementSpec`) used by the
measurements panel (US2), histogram labels (US3), level lines (US4), export headers (US5) and the
bench's demo set

**⚠️ CRITICAL**: No user story work beyond US1 can begin until this phase is complete

- [X] T002 [P] Write the vocabulary part of `tests/unit/test_analysis.py` (contract guarantee 13):
  every `Kind` has the unit and level count of the data-model.md table (`DELTA_T` s/2,
  `TIME_AT_LEVEL` s/1, `EDGE_COUNT` —/1, `AMPLITUDE`/`BASE`/`TOP`/`MAXIMUM`/`MINIMUM`/`PK_PK`/
  `MEAN` V/0, `AREA` V·s/0, `RISE_TIME`/`FALL_TIME`/`WIDTH`/`PERIOD` s/0, `FREQUENCY` Hz/0,
  `DUTY_CYCLE` %/0); `Level.label()` gives `↑ 30 mV`, `↓ -400 mV`, `lead 20%`, `trail 50%`;
  `MeasurementSpec.name` gives `Δt C2 ↑ 30 mV → C4 ↓ -400 mV` and `Amplitude C2`;
  `to_dict`/`from_dict` round-trips every kind (enum *names* stored, not labels); `from_dict`
  raises `ValueError`/`KeyError` for an unknown kind, unknown edge, source outside
  `"C1"`…`"C4"` or missing field
- [X] T003 Implement the vocabulary in `src/scope_gui/analysis.py` per contracts/analysis.md and
  data-model.md (pure numpy, no Qt/pyvisa/driver import): `Edge` (`RISING`, `FALLING`; for
  relative levels `RISING` = leading edge base → top whatever the polarity); `Kind` with `.unit`
  and `.levels`; frozen `Level(value: float, relative: bool = False, edge: Edge = Edge.RISING)`
  ("a fraction 0–1 when `relative`", label shows 0–100 %); frozen
  `MeasurementSpec(kind, source, level, source2, level2)` (`level` used if `kind.levels ≥ 1`;
  `source2`/`level2` used if `kind is DELTA_T`, `source2` "may equal `source`"), `name`,
  `to_dict`, `from_dict`; keep SI formatting of labels in one helper; make T002 pass

**Checkpoint**: Measurement definitions exist and serialise; analysis maths can be added per story

---

## Phase 3: User Story 1 - Synthetic signal bench (Priority: P1) 🎯 MVP

**Goal**: A developer command opens the normal window connected to a synthetic WR610Zi (behind
the real `ScopeDriver`) showing clock, positive and negative SiPM pulses and a NIM pulse, with
known true values; unreachable from `scope-gui`

**Independent Test**: `uv run python tests/bench.py`, press Connect → identity
`LECROY WR610ZI SYNTHETIC`, title "Scope GUI — SYNTHETIC test bench", four live traces with
photoelectron steps, empty acquisitions and dark counts (quickstart B1)

### Tests for User Story 1

> Write these tests first and make sure they fail before the implementation

- [X] T004 [P] [US1] Write `tests/integration/test_no_synthetic_in_app.py`: no file under
  `src/scope_gui/` contains `synthetic` (case-insensitive) or imports from `tests`; importing
  `scope_gui.__main__` does not import `synthetic_scope` (check `sys.modules`) — FR-001,
  Constitution I/IV
- [X] T005 [P] [US1] Write the scene part of `tests/integration/test_bench_accuracy.py` (fixed
  seeds, `SyntheticAcquisition` directly, no GUI): default `Scene` values equal data-model.md
  (10 MHz clock 0–2.5 V; SiPM A positive / B negative, Poisson mean 3, 20 mV per photoelectron,
  10 % gain spread, rise 1 ns, decay 30 ns, arrivals 35 / 37 ns, jitter 70 / 90 ps, dark rate
  1 MHz, noise 1.2 mV rms band-limited to 1 GHz; NIM −0.8 V × 20 ns, 8 ns after A crosses
  30 mV; 50 ns/div; channels C1 1 V/−0.25 V, C2 20 mV/−0.06 V, C3 20 mV/+0.06 V,
  C4 0.5 V/+1.0 V); over 2,000 acquisitions the mean of `npe_a` is 3 ± 0.15, the share
  with `npe_a == 0` is e⁻³ ≈ 5 % ± 1.5 %; `fired` is false whenever `npe_a == 0` and C4 then stays at
  0 V; true arrival σ of `arrival_b − arrival_a` is √(70² + 90²) ≈ 114 ps ± 10 %; same seed →
  identical volts (FR-002, FR-003, US1-3)
- [X] T006 [P] [US1] Write the connection part of `tests/integration/test_bench_live.py`
  (pytest-qt, `SyntheticScope` → `synthetic_factory` → real `ScopeDriver` → `MainWindow`,
  `driver.tcp_precheck` monkeypatched as in feature 001's tests, `rate_hz` high): Connect shows
  identity `SYNTHETIC` without the unsupported-model dialog; within 5 s all four curves are
  drawn and change between acquisitions; every command written to the resource is in
  `driver.ALLOWED_COMMANDS`; all channels' `WF? ALL` blocks of one acquisition carry the same
  trigger time; codes are clipped to −128…127 (a scene with C2 at 2 mV/div saturates and the
  decoded volts stop at the screen edge)

### Implementation for User Story 1

- [X] T007 [US1] Rework `tests/synthetic_scope.py` per data-model.md "Synthetic scene" and
  contracts/synthetic-bench.md: `Scene` dataclass with the defaults listed in T005 plus
  `points` (10,000), `trigger_delay`, `time_per_div` and `channels` (`ChannelSetup` V/div,
  offset, enabled, coupling); `SyntheticAcquisition(scene, rng)` with `volts` per channel and
  true values `npe_a`, `npe_b`, `arrival_a`, `arrival_b`, `fired`; SiPM pulses as double
  exponentials with Poisson photoelectrons and gain spread, dark counts at random times, noise
  Gaussian-filtered to the scene bandwidth (R13), NIM pulse fired when A crosses the
  discriminator level; `SyntheticScope(scene, rate_hz=20, seed=None)` answering
  `write`/`read_raw`/`read`/`query`/`clear`/`close` like `fakes.FakeVisaResource`: allowlisted
  queries with SHORT headers from `scene` (`*IDN` → `LECROY,WR610ZI,SYNTHETIC,9.1.0`, trigger
  mode `NORM`, `GRID SINGLE`), `Cn:WF? DESC` starts a new acquisition no faster than `rate_hz`
  (sleeping in the calling thread), `Cn:WF? ALL` serves a `fakes.build_wavedesc` block (BYTE
  codes at 25 codes/div, channel offset, clipped to −128…127, one trigger time per
  acquisition), unknown commands → no reply → `fakes._timeout_error()`; attributes `scene`,
  `current`, `acquisitions`; `synthetic_factory(scope)` like `fakes.fake_factory`; changing
  `scene` between acquisitions changes the next status read (for FR-022 tests); make T005 pass
- [X] T008 [US1] Create `tests/bench.py` per contracts/synthetic-bench.md: argparse `--rate`
  (20), `--points` (10000), `--seed`, `--mean-pe` (3); call
  `scope_gui.__main__.setup_logging()`; replace `scope_gui.settings._settings` in this process
  only with a `QSettings` INI file at `%LOCALAPPDATA%\scope_gui\bench.ini` (as
  `tests/conftest.py` does), so the real last address and measurement list are never touched;
  disable `driver.tcp_precheck` in this process only; open `MainWindow(address,
  driver_factory=…)` whose factory builds `ScopeDriver(synthetic_factory(scope))`; set the
  window title "Scope GUI — SYNTHETIC test bench"; runnable as
  `uv run python tests/bench.py` from the repo root (Python puts `tests/` on `sys.path` for the
  script, so import `from synthetic_scope import …` exactly as the tests do with
  `from fakes import …`; no path manipulation, no `tests.` package); make T004 and T006 pass

**Checkpoint**: The bench runs and shows the four signals; nothing in `src/` knows about it

---

## Phase 4: User Story 2 - Measurements with running statistics (Priority: P1)

**Goal**: User-defined measurements computed once per received acquisition, with a table of
last/mean/σ/min/max/N/missed, edit/remove/clear, remembered between sessions

**Independent Test**: On the bench (`--mean-pe 20`) add "Δt C2 lead 20 % → C3 lead 20 %" and
"Frequency C1"; after a few hundred acquisitions the Δt mean is within 20 ps of 2 ns, its σ
within 10 % of the combined jitter, and the frequency reads 10 MHz (quickstart B10, B12)

### Tests for User Story 2

- [X] T009 [P] [US2] Add the measurement guarantees 1–10 of contracts/analysis.md to
  `tests/unit/test_analysis.py`, using analytic `Waveform`s: (1) linear ramp crossing a volt
  level between samples → crossing time within 1 % of `dt`, rising and falling (SC-003);
  (2) two identical edges shifted by τ (not a multiple of `dt`) → Δt = τ ± 1 % `dt`;
  (3) constant-fraction Δt of two same-shape pulses with different amplitude *and* polarity →
  their shift, independent of amplitude; (4) square wave with several periods and a cut first
  edge → frequency within 0.1 %, duty cycle within 0.5 %, rise time within 2 % of the edge
  model; (5) pulse on noise → base ≈ baseline, top = peak, negative pulse → negative amplitude,
  Area of a rectangle = height × width; (6) noise only → percentage levels, rise/fall, width,
  period, duty cycle are NaN while amplitude is measured (FR-007a, |top − base| < 5 × noise
  rms); a perfectly flat record and a record with a single one-code step (noise below one
  digitiser step, MAD = 0) are likewise missed, because the noise is floored at one digitiser
  step; reference levels on a 2.5M-point record equal those on the full record within one
  digitiser step although only ≤ 100k samples are used; (7) noise riding on a level → one crossing per real edge (hysteresis); (8) gate → values
  from gated samples only, base from the whole record, gate with < 2 samples → NaN;
  (9) missing source channel → NaN, other measurements unaffected; (10) `Statistics` ring wraps
  at capacity, `history()` oldest first, NaN counted as missed, `summary()` (ddof = 1) matches
  numpy on the finite values, empty summary → NaN fields and count 0
- [X] T010 [P] [US2] Add to `tests/unit/test_settings.py`: `save_measurements` /
  `load_measurements` round-trip a list of `MeasurementSpec`s under the key
  `analysis/measurements`; default is an empty list; an invalid or unknown entry in the stored
  JSON is skipped (and logged) while the valid ones load (R12)
- [X] T011 [P] [US2] Write `tests/integration/test_measurements_panel.py` (pytest-qt, analytic
  `Waveform`s fed to the panel): Add via the dialog appends a row named after the spec;
  `process(waveforms)` adds exactly one value per measurement per call (FR-008); columns
  Measurement, Last, Mean, σ, Min, Max, N, Missed with SI units, 4 significant digits, % with
  2 decimals, "—" when undefined; a missed value increments Missed only; Clear empties all
  statistics and hides the settings note; editing one measurement clears only its statistics;
  Remove drops the row and its statistics; the list is saved and restored by a new panel
  (FR-011); dialog: level fields hidden for kinds without levels, second source/level only for
  Δt, "%" shows Leading/Trailing instead of Rising/Falling, OK disabled until valid
- [X] T012 [P] [US2] Extend `tests/integration/test_bench_live.py`: with two measurements on the
  live bench, after N acquisitions each measurement has exactly N entries and the trigger-time
  log has N entries; while paused N does not grow (FR-023) and resumes after; hidden channels
  are still measured (FR-008); changing `scope.scene` V/div mid-run shows "Scope settings
  changed during this run" and keeps the statistics (FR-022, R14), Clear hides it; after
  Disconnect, and after a lost connection (resource raising), the table still shows the same N
  and statistics (spec Edge Cases); still only allowlisted commands written (FR-020)
- [ ] T013 [P] [US2] Add to `tests/integration/test_bench_accuracy.py` (fixed seeds,
  `SyntheticAcquisition` → `Waveform`s → `measure_all`, no GUI): with `mean_pe=20`, 2,000
  acquisitions, Δt C2 lead 20 % → C3 lead 20 % has mean within 20 ps of 2,000 ps and sample σ
  within 10 % of the true combined jitter of those acquisitions; with the default scene
  Frequency C1 within 0.1 % of 10 MHz (SC-002 frequency part)

### Implementation for User Story 2

- [X] T014 [US2] Implement measurements in `src/scope_gui/analysis.py` per data-model.md "Kind"
  and research R1–R4: `Trace` (whole-record base and noise rms by MAD × 1.4826, polarity
  +1/−1/0 by mid-level split with `PULSE_FRACTION = 0.2`, all computed on at most 100,000
  evenly spaced samples of the record (R1); gated top = peak over every gated sample for
  pulses, record top for square-like); noise rms floored at one digitiser step (the
  waveform's gain per code; add it to `Waveform` if not available from the descriptor);
  `MIN_SNR = 5.0` (amplitude-relative quantities missed when |top − base| < 5 × noise rms); hysteresis max(5 % of amplitude, 3 × noise rms); vectorised
  crossing scan with linear interpolation and first-crossing semantics; relative levels
  `base + f × (top − base)` with the edge flipped for negative polarity; rise/fall time on the
  first complete edge; width, period (≥ 2 leading crossings), frequency, duty cycle over
  complete cycles; `measure_all(specs, waveforms, gate=None) -> list[float]` building one
  `Trace` per channel per acquisition, NaN for missed, under `np.errstate`; `Statistics`
  (float64 ring of `HISTORY = 100_000`, `add`, `clear`, `size`, `history`, `values`, `last`,
  `summary`) and frozen `Summary(last, mean, std, minimum, maximum, count, missed)`; make T009
  and T013 pass
- [X] T015 [P] [US2] Add `load_measurements() -> list[MeasurementSpec]` and
  `save_measurements(specs)` to `src/scope_gui/settings.py`: JSON list of `to_dict()` under
  `analysis/measurements`, invalid entries skipped with a log warning; make T010 pass
- [X] T016 [P] [US2] Create `src/scope_gui/ui/measurement_dialog.py` per contracts/ui.md
  "Add… / Edit…": type combo (all `Kind`s, with a tooltip giving each definition from
  data-model.md), source combo C1–C4, level value + unit (V or %) + edge (Rising/Falling, shown
  as Leading/Trailing for %) shown only when `kind.levels ≥ 1`, second source + level only for
  `DELTA_T`; `%` stored as fraction 0–1; OK disabled until valid; returns a `MeasurementSpec`
  or `None`
- [X] T017 [US2] Create `src/scope_gui/ui/measurements_panel.py`: buttons Add…, Edit…
  (also row double-click), Remove, Clear (Export… added in US5); table per contracts/ui.md;
  one `Statistics` per measurement and the `AcquisitionLog` ring of trigger times (first
  channel's `Waveform.trigger_time`) filled in step; `process(waveforms)` measures once and
  refreshes the table; `selected_spec` and a `selection_changed` signal; hidden
  "⚠ Scope settings changed during this run" label with `set_settings_changed()` (shown only
  while statistics hold values) cleared by Clear; persist the list with
  `settings.save_measurements` on every add/edit/remove and load it at construction; make T011
  pass
- [X] T018 [US2] Wire analysis in `src/scope_gui/ui/main_window.py`: Measurements dock
  (bottom, movable/floatable/closable) and a View menu entry to re-open it; default size
  1400 × 900; in `_on_waveforms` call `measurements_panel.process(waveforms)` with every
  received channel (also hidden ones) only when not paused (FR-008, FR-023); in `_on_status`
  compare channel settings, timebase, trigger delay and trigger mode with the previous
  `ScopeStatus` (ignore `acq_state`/`read_at`) and call `set_settings_changed()` on a change
  (R14); keep statistics on disconnect/connection lost; make T012 pass
- [X] T019 [US2] In `tests/bench.py` add the demo measurement set of
  contracts/synthetic-bench.md on first start (when `load_measurements()` is empty): Δt C2
  lead 20 % → C3 lead 20 %; Δt C2 ↑ 30 mV → C4 ↓ −400 mV; Δt C1 ↑ 1.25 V → C2 ↑ 30 mV;
  Amplitude C2; Area C2; Frequency C1; Rise time C2

**Checkpoint**: US1 + US2 give a working measurement bench; the real app gains measurements

---

## Phase 5: User Story 3 - Distributions: histogram, trend and correlation (Priority: P2)

**Goal**: Histogram (bins, robust/full/manual range, log, Gaussian fit), trend and correlation of
the selected measurement

**Independent Test**: On the bench, "Amplitude C2" with Log and 200 bins shows separate
photoelectron peaks 20 mV ± 5 % apart; the constant-fraction Δt fit gives a mean within 20 ps
of 2 ns and σ within 15 % of 114 ps (quickstart B2, B4, B5)

### Tests for User Story 3

- [ ] T020 [P] [US3] Add guarantees 11–12 to `tests/unit/test_analysis.py`: `gauss_fit` on a
  sampled Gaussian with a second smaller peak and tails → mean and σ within 5 %, `fwhm` =
  2.3548 σ; `None` for < 10 entries or a flat histogram; `histogram_range(values,
  RangeMode.AUTO_ROBUST)` with 25 % outliers → contains ≥ 95 % of the main peak and excludes
  the far outliers (median ± 8 robust σ); `FULL` → min–max; `MANUAL` → the given (from, to);
  constant values → a non-empty range
- [ ] T021 [P] [US3] Add to `tests/integration/test_bench_accuracy.py`: with `mean_pe=20`,
  2,000 acquisitions, `gauss_fit` of the constant-fraction Δt histogram → σ within 10 % of the
  true combined jitter and mean within 20 ps of 2,000 ps (SC-002); default scene, Amplitude C2
  histogram shows ≥ 4 peaks spaced by 20 mV ± 5 % (SC-004; find peaks as local maxima of the
  histogram); default scene, fitted Δt mean within 20 ps of 2 ns and σ within 15 % (US3
  Independent Test); a scene with C2 at 5 mV/div clips large pulses and the amplitude
  histogram's highest bin sits at the clipping level (spec Edge Cases)
- [ ] T022 [P] [US3] Write `tests/integration/test_histogram_panel.py` (pytest-qt, statistics
  filled directly): histogram view title/x label = measurement name with unit; stats line shows
  N, outside, mean, σ; Fit on → curve drawn and μ, σ, FWHM shown, flat data → "no fit"; bins
  limited to 10–1000; Log toggles the count axis; Manual range shows from/to fields and is
  applied; trend view has gaps (NaN) for missed; correlation view plots only acquisitions where
  both exist, X = chosen measurement, at most the latest 5,000 points; selecting another row in
  the measurements panel switches the histogram

### Implementation for User Story 3

- [ ] T023 [US3] Implement in `src/scope_gui/analysis.py`: `RangeMode` (`AUTO_ROBUST` default,
  `FULL`, `MANUAL`), `histogram_range(values, mode, manual=None) -> tuple[float, float]`
  (median ± 8 robust σ, widened to a non-empty range for constant values); frozen
  `GaussFit(mean, sigma, amplitude)` with `fwhm` and `__call__`; `gauss_fit(centers, counts)`
  per R5 (weighted log-parabola on ±2 σ around the highest peak, started from the half-max
  width, iterated, `None` when no sensible fit); make T020 and T021 pass
- [ ] T024 [US3] Create `src/scope_gui/ui/histogram_panel.py` per contracts/ui.md: view
  selector Histogram | Trend | Correlation, X measurement combo (correlation; default first
  other measurement), Bins spin box (100, 10–1000), Range combo Auto / Full / Manual with
  from/to fields, Log and Fit check boxes (off, on); step histogram via `np.histogram` with SI
  axis; trend as value vs acquisition index with `connect="finite"`; correlation as
  `ScatterPlotItem` of the latest 5,000 pairs; stats line "N … · outside … · mean … · σ …" plus
  "fit μ … σ … FWHM …" or "no fit"; `show(spec, statistics, others)` refresh entry point; make
  T022 pass
- [ ] T025 [US3] Wire in `src/scope_gui/ui/main_window.py`: Histogram dock (bottom, next to the
  Measurements dock) with View menu entry; refresh it after each processed acquisition and on
  `selection_changed`; no refresh while paused (FR-023)

**Checkpoint**: Timing resolution and spectra can be read from the bench and the scope

---

## Phase 6: User Story 4 - Inspecting the waveform (Priority: P2)

**Goal**: Zoom/pan with reset, two cursors with readout, gate between cursors, draggable level
lines, fading density persistence

**Independent Test**: On the bench, box-zoom on the C1 edge, the view stays while traces update,
double-click resets; cursors 100 ns apart read Δt 100 ns and 1/Δt 10 MHz (quickstart B3, B6–B9)

### Tests for User Story 4

- [ ] T026 [P] [US4] Write `tests/unit/test_persistence.py`: a trace is rasterised per pixel
  column of a given view (x range, y range in divisions, width × height) — each column gets
  one hit on every pixel between the min and max of its samples; a fast edge with fewer
  samples than pixels fills the column span without gaps (consecutive columns connected);
  a record with fewer samples than columns is interpolated; fade factor (1 − 1/N) per
  acquisition for N in 10 / 100 / 1000 and none for Infinite; `reset()` empties the map;
  output RGB uses each channel's colour scaled by √density; channels outside the view add
  nothing
- [ ] T027 [P] [US4] Write `tests/integration/test_scope_plot_tools.py` (pytest-qt):
  a manual range change sets the zoomed flag and later `set_status` calls do not move the view
  (the grid still follows); Reset view and double-click restore the scope screen and clear the
  flag (FR-014); cursors on → two lines at 1/3 and 2/3 of the view, readout shows Δt, 1/Δt and
  per visible channel `Cn V1 V2 ΔV` interpolated from the samples, updated on drag and on new
  waveforms (FR-015); gate between cursors → shaded non-movable region following the cursors
  and the gate interval reported (FR-016); level lines → one dashed line per volt level of the
  selected measurement in the channel colour at the right division, dragging emits the new
  level on release only (FR-017); persistence on → image item behind the curves, restarted by
  zoom, reset and a V/div change, removed by Off (FR-018); paused → no persistence change;
  `clear()` keeps the zoom and cursors and empties the persistence
- [ ] T028 [P] [US4] Add to `tests/integration/test_measurements_panel.py`: Gate combo "Whole
  record" / "Between cursors"; selecting "Between cursors" requests cursors on and `process`
  passes the gate to `measure_all`; dragging a level line updates that measurement's spec (name
  shows the new level), clears only its statistics and saves the list

### Implementation for User Story 4

- [ ] T029 [P] [US4] Create `src/scope_gui/ui/persistence.py` per research R7 (numpy only):
  density map per channel over the current view (≈ 1 px per bin), `add(waveforms, view)`
  rasterising each trace as min–max spans per pixel column (`np.minimum.reduceat` /
  `np.maximum.reduceat`, spans extended to the neighbouring columns' values; measured
  1.3 ms per channel at 2.5M points),
  fade by (1 − 1/N) or none for infinite, `reset()`, `image()` → RGB colouring each layer with
  `models.CHANNEL_COLORS` at √density and summing; make T026 pass
- [ ] T030 [US4] Extend `src/scope_gui/ui/scope_plot.py` per R8–R9 and contracts/ui.md
  "Plot mouse": enable ViewBox mouse in `RectMode`, wheel zoom, middle-drag pan, context menu
  off; `sigRangeChangedManually` sets the zoomed flag and `_update_range` skips setting the
  range while zoomed; `reset_view()` and double-click; cursors (`InfiniteLine` "1"/"2") and
  top-left readout; gate `LinearRegionItem` (non-movable, follows cursors) with `gate()` →
  (t1, t2) or `None`; `set_level_lines(spec, status)` drawing dashed draggable lines for volt
  levels in divisions, keeping the dragged volts while dragging and emitting
  `level_dragged(index, volts)` on release; persistence `ImageItem` behind the curves using
  `persistence.py`, `set_persistence(n | None | 0)`, restarted on view or V/div/offset/timebase
  change; signals for gate/cursor changes; `clear()` (Disconnect / connection lost) keeps zoom
  and cursors and clears persistence with the traces (contracts/ui.md Guarantees); make T027
  pass
- [ ] T031 [P] [US4] Add the Display group to `src/scope_gui/ui/side_panel.py`: Cursors check
  box, Persistence combo (Off / 10 / 100 / 1000 / Infinite), Reset view button, with signals;
  `clear()` keeps the Display choices
- [ ] T032 [US4] Add the Gate combo (Whole record / Between cursors) to
  `src/scope_gui/ui/measurements_panel.py` and `update_level(index, volts)` that replaces the
  selected spec's level, clears only its statistics and saves the list; make T028 pass
- [ ] T033 [US4] Wire in `src/scope_gui/ui/main_window.py`: Display group → scope plot
  (cursors, persistence, reset view); gate combo ↔ cursors and pass `scope_plot.gate()` to
  `process`; selected measurement → `scope_plot.set_level_lines`; `level_dragged` →
  `measurements_panel.update_level`; persistence fed only when not paused

**Checkpoint**: All inspection tools work on the bench; measurements follow the gate and lines

---

## Phase 7: User Story 5 - Export measurements (Priority: P3)

**Goal**: CSV of all accumulated values, one row per acquisition, written off the GUI thread

**Independent Test**: 500 acquisitions × 3 measurements → file with 500 rows, header with the
three names, empty cells where missed (quickstart B11)

### Tests for User Story 5

- [ ] T034 [P] [US5] Add export tests to `tests/integration/test_measurements_panel.py`
  (`QFileDialog` monkeypatched to return a `tmp_path` file): 500 acquisitions × 3 measurements
  → header `trigger_time_s` then `name [unit]` per measurement, 500 rows, empty cell for missed,
  file starts with the UTF-8 BOM; a measurement added after 200 acquisitions has an empty
  column for the first 200 rows (US5-2, rows end-aligned per R10); the export call returns in
  < 0.2 s with 100,000 × 10 values and the write finishes in the background with a status
  message containing the path (SC-006); a failing write (read-only path) reports an error
  message instead of raising; export still works after the panel's window was disconnected
  (spec Edge Cases)

### Implementation for User Story 5

- [ ] T035 [US5] Implement export in `src/scope_gui/ui/measurements_panel.py` per R10–R11:
  Export… button, `QFileDialog.getSaveFileName` (`.csv`); copy histories and the trigger-time
  log on the GUI thread; write with `csv` (UTF-8 with BOM, `newline=""`) in a `QRunnable` on
  `QThreadPool.globalInstance()`; report done/failed through a queued signal; make T034 pass
- [ ] T036 [US5] Wire the export result signal to the status bar in
  `src/scope_gui/ui/main_window.py` ("Exported N acquisitions to <path>" / "Export failed:
  <reason>"); statistics stay exportable after Disconnect and connection lost

**Checkpoint**: All five stories functional

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T037 [P] Add to `tests/hardware/test_real_scope.py` a read-only session with analysis
  active (10 measurements, histogram shown, cursors and persistence on): every written command
  is in `ALLOWED_COMMANDS` (SC-007, FR-020)
- [ ] T038 [P] Update `README.md`: analysis features (measurements and their definitions per
  data-model.md, statistics, histogram/trend/correlation, zoom, cursors, gate, level lines,
  persistence, export); the synthetic bench as a developer tool
  (`uv run python tests/bench.py`, options, separate `bench.ini`), stating it is not a mode of
  the application; link to `specs/002-waveform-analysis/quickstart.md`
- [ ] T039 Measure `measure_all` with 10 measurements and persistence at 10k / 100k / 2.5M × 4
  channels on this PC; confirm ≤ 10 ms and ≤ 40 ms at 100k (plan Performance Goals) and a
  total GUI-thread time per acquisition (analysis + persistence + drawing) ≤ 0.2 s at 2.5M
  (FR-021, Principle II); if 2.5M exceeds it, profile and reduce before continuing; record
  the numbers in `specs/002-waveform-analysis/checklists/validation.md`
- [ ] T040 Run `uv run ruff check --fix` and `uv run ruff format`; fix remaining issues in
  `src/` and `tests/`
- [ ] T041 Run `uv run pytest` over `tests/` (must pass with no scope) and `uv run pytest -m hardware`
  against the real scope; fix failures
- [ ] T042 Run quickstart.md scenarios B1–B12 on the bench and R1–R4 on the real scope; time
  SC-001 (from a connected live view with no measurements: define a Δt between two channels
  and see its histogram with a Gaussian fit, target < 1 minute); record results in
  `specs/002-waveform-analysis/checklists/validation.md`
- [ ] T043 Set `**Status**` in `specs/002-waveform-analysis/spec.md` to Implemented, amending
  any success criterion whose measured value differs (as done for 001's SC-002)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after Setup; blocks US2–US5 (they all use `MeasurementSpec`).
- **US1 (Phase 3)**: after Setup only; independent of Phase 2, so it can run alongside it.
- **US2 (Phase 4)**: after Phase 2. Uses the bench (US1) for T012, T013 and T019; the
  analysis and panel tasks do not need it.
- **US3 (Phase 5)**: after US2 (needs `Statistics` and the panel's selection).
- **US4 (Phase 6)**: after US2 (gate and level lines act on measurements); independent of US3.
- **US5 (Phase 7)**: after US2; independent of US3 and US4.
- **Polish (Phase 8)**: after the stories to be delivered.

### Within Each Story

- Tests are written first and fail, then implementation makes them pass.
- `analysis.py` → widgets → `main_window.py` wiring.
- Tasks editing the same file run in order: `analysis.py` T003 → T014 → T023;
  `measurements_panel.py` T017 → T032 → T035; `main_window.py` T018 → T025 → T033 → T036;
  `test_analysis.py` T002 → T009 → T020; `test_bench_accuracy.py` T005 → T013 → T021;
  `test_measurements_panel.py` T011 → T028 → T034; `tests/bench.py` T008 → T019.

### Parallel Opportunities

- Phase 2 ∥ US1 (different files).
- US1: T004 ∥ T005 ∥ T006.
- US2: T009 ∥ T010 ∥ T011 ∥ T012 ∥ T013; then T015 ∥ T016 alongside T014.
- US3: T020 ∥ T021 ∥ T022.
- US4: T026 ∥ T027 ∥ T028; T029 ∥ T031.
- After US2: US3, US4 and US5 can proceed in parallel except for their `main_window.py` and
  `measurements_panel.py` wiring tasks, which run one after another.
- Polish: T037 ∥ T038.

---

## Parallel Example: User Story 2

```text
Task: "Add measurement guarantees 1–10 to tests/unit/test_analysis.py"      (T009)
Task: "Add measurement list tests to tests/unit/test_settings.py"           (T010)
Task: "Write tests/integration/test_measurements_panel.py"                  (T011)
Task: "Extend tests/integration/test_bench_live.py"                         (T012)
Task: "Add SC-002 mean/σ and frequency to test_bench_accuracy.py"           (T013)
# then, alongside T014 (analysis.py):
Task: "Add load/save_measurements to src/scope_gui/settings.py"            (T015)
Task: "Create src/scope_gui/ui/measurement_dialog.py"                      (T016)
```

---

## Implementation Strategy

### MVP First (User Stories 1 and 2, both P1)

1. Phase 1 Setup → Phase 2 Foundational and Phase 3 US1 (bench).
2. Phase 4 US2 → validate on the bench (B10, B12) and briefly on the real scope (R4).
3. **STOP and VALIDATE**: measurements with statistics are the core of the feature.

### Incremental Delivery

1. MVP (US1 + US2) → commit.
2. US3 distributions → validate B2, B4, B5 → commit.
3. US4 inspection → validate B3, B6–B9 → commit.
4. US5 export → validate B11 → commit.
5. Polish → full test run, hardware session, manual validation B1–B12 and R1–R4.

---

## Notes

- Nothing in this feature sends a command to the scope; the allowlist test of feature 001 and
  T006/T012/T037 guard FR-020.
- The synthetic scope lives only in `tests/`; T004 guards that `src/` never reaches it.
- Analysis runs on the GUI thread (R1); only the CSV write goes to a background thread (R11).
- Commit after each task group; never push.
