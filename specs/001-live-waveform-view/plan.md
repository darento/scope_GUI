# Implementation Plan: Live Waveform View

**Branch**: `001-live-waveform-view` | **Date**: 2026-10-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-live-waveform-view/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

A PySide6 desktop app that connects to the lab's LeCroy WR610Zi over VXI-11 and mirrors its
live waveforms (channels C1–C4) on the PC, on the same 10 × 8 division grid, with the same
scales, offsets, timebase, trigger position and colours. It is strictly read-only towards the
scope. A single driver module talks to the instrument using a fixed allowlist of verified
queries; a worker thread polls settings (~2 ms per query) and transfers full records
(`Cn:WF? ALL`) only when a new acquisition is detected via the descriptor's trigger timestamp
(~4 ms check). Measured scope readout is ~2.2 MB/s, giving ≥ 5 Hz at 100k points × 4 channels
and ~1.5 Hz at the current 500k points × 3 channels, with the achieved rate shown in the UI.

## Technical Context

**Language/Version**: Python 3.13 (64-bit CPython, uv-managed)

**Primary Dependencies**: PySide6 (GUI), pyvisa + pyvisa-py (VXI-11, no NI-VISA), numpy
(decoding), pyqtgraph (fast plotting with peak downsampling)

**Storage**: N/A — only the last address in `QSettings`; rotating log file in
`%LOCALAPPDATA%\scope_gui\logs`

**Testing**: pytest + pytest-qt; fake VISA resource in `tests/` replaying responses captured from
the real scope; `@pytest.mark.hardware` tests against the real scope, skipped by default

**Target Platform**: Windows 11 (lab PCs), USB-GbE adapter on the scope's subnet

**Project Type**: desktop-app (single project)

**Performance Goals**: ≥ 5 display updates/s at 4 ch × 100k points (SC-002); UI input latency
< 0.2 s always (SC-003); settings changes reflected < 2 s (FR-014)

**Constraints**: read-only towards the scope (FR-018) — allowlisted queries only; connect
outcome ≤ 10 s (FR-006); loss detection ≤ 5 s (FR-007); scope readout ceiling ~2.2 MB/s
(measured, R2); unknown queries time out instead of erroring (R4)

**Scale/Scope**: 1 user, 1 scope, 4 analog channels, records up to ~2.5 M points/channel

No NEEDS CLARIFICATION remain; all unknowns resolved in [research.md](research.md) (R1–R12),
mostly by measurement on the real scope.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution v2.0.0.

| Principle | Pre-design | Post-design | Evidence |
|-----------|-----------|-------------|----------|
| I. Hardware behind a driver layer (real driver only, no simulation) | PASS | PASS | Only `driver.py` imports pyvisa / formats commands ([contracts/scope-driver.md](contracts/scope-driver.md)); no simulated mode anywhere ([contracts/ui.md](contracts/ui.md)); FR-009 |
| II. Responsive UI | PASS | PASS | All I/O in one worker `QThread`, signals only; finite timeouts; abort-on-close strategy (R8) |
| III. Safe by default | PASS | PASS | Read-only allowlist enforced by a unit test; `CFMT`/`CHDR`/`WFSU` never written (R3); `INR?` avoided because it clears state (R5) |
| IV. Testable without hardware | PASS | PASS | Fake VISA resource in `tests/` only, fed with captured real responses; hardware tests marked and skipped by default |
| V. Simple and pragmatic | PASS | PASS | One package, flat modules, no plugin/config frameworks; new deps justified: pyqtgraph (R7), numpy (R7/decoding) |
| Tech constraints (Py 3.13, PySide6 only, pyvisa-py, uv, configurable address) | PASS | PASS | R1, R9, R12; address field + QSettings, never hard-coded in logic |

No violations; Complexity Tracking not needed.

## Project Structure

### Documentation (this feature)

```text
specs/001-live-waveform-view/
├── plan.md              # This file
├── research.md          # Phase 0: measured scope behaviour + decisions
├── data-model.md        # Phase 1: entities, connection state machine
├── quickstart.md        # Phase 1: setup, tests, manual validation on the real scope
├── contracts/
│   ├── scope-driver.md  # Driver interface + read-only command allowlist
│   └── ui.md            # Window layout, controls, guarantees
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
pyproject.toml           # uv project; entry point scope-gui = scope_gui.__main__:main
uv.lock
src/scope_gui/
├── __init__.py
├── __main__.py          # main(): logging setup, QApplication, MainWindow
├── models.py            # dataclasses/enums from data-model.md
├── wavedesc.py          # pure parsing: IEEE 488.2 block, WAVEDESC, sample decoding
├── driver.py            # ScopeDriver: the ONLY pyvisa/command code; allowlist enforcement
├── worker.py            # AcquisitionWorker (QObject in QThread): poll loop, signals
├── settings.py          # QSettings wrapper (last address), log folder path
└── ui/
    ├── __init__.py
    ├── main_window.py   # layout, wiring worker signals ↔ widgets, close handling
    ├── connection_bar.py# address, connect/disconnect, status indicator, identity
    ├── scope_plot.py    # pyqtgraph plot: 10×8 div grid, traces, trigger marker, stale overlay
    └── side_panel.py    # channel checkboxes/settings, acquisition info, pause

tests/
├── conftest.py          # registers `hardware` marker, skips unless -m hardware
├── fakes.py             # FakeVisaResource replaying captured replies (tests only)
├── fixtures/            # captured real replies: *IDN?, settings, WF? DESC bytes
├── unit/
│   ├── test_wavedesc.py # parsing/decoding, byte & word, endianness, malformed blocks
│   ├── test_driver.py   # replies parsing, allowlist enforcement, errors, recover()
│   └── test_models.py   # support classification, div/volt mapping
├── integration/
│   ├── test_worker.py   # pytest-qt: state machine, novelty detection, loss/recovery
│   └── test_ui.py       # pytest-qt: connect flow, hide/pause, no-channels message, stale
└── hardware/
    └── test_real_scope.py  # -m hardware: identity, read-only session, settings unchanged
```

**Structure Decision**: Single `src/`-layout package `scope_gui` with flat modules; the
`ui/` subpackage only groups widgets. Tests split into unit (pure logic), integration (Qt +
fake instrument) and hardware (real scope, opt-in).

## Complexity Tracking

Not applicable — Constitution Check has no violations.
