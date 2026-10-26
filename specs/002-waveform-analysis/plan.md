# Implementation Plan: Waveform Analysis

**Branch**: `002-waveform-analysis` | **Date**: 2026-10-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-waveform-analysis/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Add PC-side analysis to the live view, plus a synthetic test bench to develop and demonstrate it
without the scope.

- **Bench**: a VISA-resource stand-in in `tests/` that generates the lab's typical signals:
  clock, positive/negative SiPM pulses with photoelectron statistics, jitter, dark counts and
  band-limited noise, and a NIM discriminator. It sits behind the real `ScopeDriver`, so the
  allowlist, decoding and worker loop are exercised unchanged.
- **Analysis**: a pure-numpy module `analysis.py` computes user-defined measurements from each
  received acquisition on the GUI thread (≤ 7 ms at 100k × 4, research R1):
  - Δt between level crossings of any channels (volts or constant fraction, interpolated),
    pulse and square-wave parameters;
  - ring-buffer statistics;
  - robust histogram range and Gaussian fit.
- **New widgets**: a measurements dock (table, add/edit dialog, gate, export), a histogram dock
  (histogram, trend, correlation).
- **Scope plot**: gains zoom/pan, cursors, gate shading, draggable level lines and a
  density-image persistence.
- **Read-only**: nothing new is sent to the scope.

## Technical Context

**Language/Version**: Python 3.13 (64-bit CPython, uv-managed)

**Primary Dependencies**: PySide6, pyqtgraph, numpy (all existing; no new dependencies, R15)

**Storage**: `QSettings` key `analysis/measurements` (JSON list of measurement definitions);
CSV files written on user request. The bench uses its own settings file.

**Testing**: pytest + pytest-qt.
- Unit tests of `analysis.py` with analytic signals.
- Accuracy tests on the synthetic bench with fixed seeds (SC-002–SC-004).
- Qt tests of the new panels and plot tools.
- An end-to-end test with `SyntheticScope` behind the real driver and worker.
- The existing hardware tests are extended with an allowlist check while analysis is active.

**Target Platform**: Windows 11 lab PCs

**Project Type**: desktop-app (single project)

**Performance Goals**: Analysis ≤ 10 ms per acquisition at 100k × 4 with 10 measurements
(measured 7.3 ms); persistence ≤ 40 ms per update at 100k × 4 (measured 34 ms); update rate
on the real scope within 10 % of the rate without analysis (SC-005); UI input latency < 0.2 s.

**Constraints**:
- Strictly read-only (FR-020): the allowlist is unchanged.
- The synthetic scope must not be reachable from `src/` (Constitution I/IV).
- File writes happen off the GUI thread (Constitution II).
- History is capped at 100,000 values per measurement (0.8 MB each).

**Scale/Scope**: 1 user, 4 channels, up to ~20 measurements, records up to ~2.5 M points.
At 2.5 M × 4 the prototype took 304 ms per acquisition, above the 0.2 s responsiveness limit;
with reference levels taken from ≤ 100k evenly spaced samples (R1) and persistence rasterised
per pixel column (R7) the expected GUI-thread cost is ≈ 0.15 s, confirmed by T039.

All unknowns were resolved by measurement in [research.md](research.md) (R1–R15). No NEEDS
CLARIFICATION remain.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution v2.0.0.

| Principle | Pre-design | Post-design | Evidence |
|-----------|-----------|-------------|----------|
| I. Hardware behind a driver layer (real driver only, no simulation) | PASS | PASS | `analysis.py` and the new widgets never touch the driver; the synthetic scope is a *resource* stand-in under `tests/` used through the unchanged `ScopeDriver` (R13). The app has no simulated mode: `scope-gui` cannot reach it, which a test enforces ([contracts/synthetic-bench.md](contracts/synthetic-bench.md)) |
| II. Responsive UI | PASS | PASS | Analysis on the GUI thread costs ≤ 7 ms per update at 100k × 4 and 57 ms at 500k (R1, below the 0.2 s limit); at 2.5M the reference levels use ≤ 100k samples to stay below it (R1); persistence 34 ms, rasterised per pixel column so it barely grows with record length (R7); CSV export in a `QThreadPool` task (R11) |
| III. Safe by default | PASS | PASS | No new commands; `ALLOWED_COMMANDS` unchanged; allowlist test unchanged; hardware session check repeated with analysis active (SC-007) |
| IV. Testable without hardware | PASS | PASS | Everything is testable on the bench or with analytic signals; the bench and fakes live only in `tests/`; hardware checks stay opt-in |
| V. Simple and pragmatic | PASS | PASS | No new dependencies (scipy rejected, R5); one pure module plus three widgets; no plugin or measurement framework: a flat `Kind` enum and one `measure()` function |
| Tech constraints (Py 3.13, PySide6 only, pyvisa-py, uv) | PASS | PASS | Unchanged stack |

No violations; Complexity Tracking not needed.

Spec 001's statement "no simulated or demo mode" (FR-009) is respected: the bench is a
developer tool in `tests/`, not a mode of the application. README wording is updated to say so.

## Project Structure

### Documentation (this feature)

```text
specs/002-waveform-analysis/
├── plan.md              # This file
├── research.md          # Phase 0: prototype measurements and decisions (R1–R15)
├── data-model.md        # Phase 1: measurement kinds, statistics, view state, synthetic scene
├── quickstart.md        # Phase 1: bench + real-scope validation scenarios
├── contracts/
│   ├── ui.md            # Docks, dialog, plot tools, guarantees
│   ├── analysis.md      # analysis module interface + behavioural guarantees
│   └── synthetic-bench.md  # bench launcher and SyntheticScope behaviour
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
src/scope_gui/
├── analysis.py              # NEW pure numpy: Kind/Level/MeasurementSpec, Trace, measure_all,
│                            #     Statistics/Summary, histogram_range, gauss_fit
├── settings.py              # + load_measurements / save_measurements (QSettings JSON)
└── ui/
    ├── main_window.py       # + docks, View menu, analysis wiring, pause, settings-changed check
    ├── scope_plot.py        # + zoom/reset, cursors + readout, gate region, level lines,
    │                        #     persistence image
    ├── persistence.py       # NEW density map accumulation/colouring (numpy) for the plot
    ├── side_panel.py        # + Display group: Cursors, Persistence, Reset view
    ├── measurements_panel.py# NEW table, buttons, gate, settings note, statistics, CSV export
    ├── measurement_dialog.py# NEW add/edit dialog
    └── histogram_panel.py   # NEW histogram / trend / correlation, bins, range, log, fit

tests/
├── synthetic_scope.py       # NEW Scene, SyntheticAcquisition, SyntheticScope, synthetic_factory
├── bench.py                 # NEW launcher: uv run python tests/bench.py
├── unit/
│   ├── test_analysis.py     # NEW contract guarantees 1–13 (analytic signals)
│   ├── test_persistence.py  # NEW binning, fading, reset
│   └── test_settings.py     # + measurement list round trip, invalid entries skipped
├── integration/
│   ├── test_bench_accuracy.py   # NEW SC-002/SC-004 on SyntheticAcquisition with fixed seeds
│   ├── test_bench_live.py       # NEW SyntheticScope → driver → worker → window → measurements
│   ├── test_measurements_panel.py # NEW add/edit/remove/clear, missed, pause, note, export
│   ├── test_histogram_panel.py  # NEW views, range modes, fit display
│   ├── test_scope_plot_tools.py # NEW zoom/reset, cursors readout, gate, level drag, persistence
│   └── test_no_synthetic_in_app.py # NEW src/ never imports tests code
└── hardware/
    └── test_real_scope.py   # + allowlist-only session with analysis active (SC-007)
```

**Structure Decision**: Same single package. Analysis maths goes in one pure module next to
`wavedesc.py`; each new visible area gets one widget module under `ui/`. The bench lives next
to `fakes.py` and reuses its `build_wavedesc`.

## Complexity Tracking

Not applicable: the Constitution Check has no violations.
