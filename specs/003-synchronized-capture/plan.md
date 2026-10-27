# Implementation Plan: Synchronized Capture

**Branch**: `003-synchronized-capture` | **Date**: 2026-10-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-synchronized-capture/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

While the scope runs, each channel read returns that channel's newest acquisition, so the app
shows and measures channels from different triggers (measured: 20 of 20 reads mixed, R1).

- **Synchronized capture** (opt-in): the worker arms one acquisition with `ARM`, reads the
  status while the scope acquires, polls `TRMD?` until `STOP`, reads all channels and only then
  arms again (R2, R3). From Auto it forces a trigger with `FRTR` after 0.5 s (R4). It restores
  the remembered trigger mode with `TRMD <mode>` on switch-off, disconnect and close (R5), and
  reports the remembered mode in its status so the settings-changed note does not fire (R7).
- **Driver**: a second, separate allowlist for the three control commands, sent through a new
  `_write`; the read-only allowlist is untouched.
- **Normal mode**: the window flags updates whose channels have different trigger times and the
  measurements skip cross-channel values (and correlation pairs) for them (R9, R10).
- **Bench**: the synthetic scope follows its trigger mode like the WR610Zi, so mixed reads and
  the mode are reproducible without hardware (R11).

## Technical Context

**Language/Version**: Python 3.13 (64-bit CPython, uv-managed)

**Primary Dependencies**: PySide6, pyqtgraph, numpy, pyvisa + pyvisa-py (all existing; none
new)

**Storage**: none new; the mode is never persisted (FR-001)

**Testing**: pytest + pytest-qt.
- Unit: control allowlist (each command accepted/refused), driver control methods against
  `FakeVisaResource`, `check_log` with control commands.
- Integration on the bench: worker state machine (arm/poll/force/restore/external change/
  link lost/pause), window switch and indicators, mixed-update flag, measurements and
  correlation skipping, close restores.
- Hardware (opt-in): switch on/off from Auto, Normal and Stopped restores the mode; coherent
  reads with the mode on.

**Target Platform**: Windows 11 lab PCs, WR610Zi firmware 9.1.0

**Project Type**: desktop-app (single project)

**Performance Goals**: ≥ 5 synchronized updates/s at 2 µs/div, 200k points, 2 channels
(estimated 6–7, R3); restore within 2 s of switch-off/disconnect/close (R8); GUI unchanged
(all scope I/O stays in the worker).

**Constraints**:
- Only `ARM`, `FRTR`, `TRMD <remembered mode>` may be written, and only while the user has the
  mode on (constitution v2.1.0 III).
- Mode off: byte-for-byte the same commands as before (SC-004).
- Front-panel Stop cannot be detected while the mode is on (spec, R6).

**Scale/Scope**: 1 user, 1 scope, 4 channels, records up to 2.5M points.

All unknowns were resolved by measurement in [research.md](research.md) (R1–R13). No NEEDS
CLARIFICATION remain.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution v2.1.0.

| Principle | Pre-design | Post-design | Evidence |
|-----------|-----------|-------------|----------|
| I. Hardware behind a driver layer | PASS | PASS | The three control commands exist only in `driver.py` (`arm`, `force_trigger`, `restore_trigger_mode`); the worker calls methods, the GUI only signals |
| II. Responsive UI | PASS | PASS | Arming and polling run in the worker as short timer cycles (≤ 10 ms polls); restore runs between cycles (R8); close waits ≤ 3 s only while the mode is on; mixed detection is a set comparison per update |
| III. Safe by default — Acquisition control | PASS | PASS | Off by default and never persisted; explicit checkbox; amber indicator while on; separate `CONTROL_COMMANDS` allowlist enforced in `_write` and tested; only arming, forcing (Auto only) and restoring the remembered mode; restore on switch-off/disconnect/close, user told on link loss; INFO logs for on/off/restore with counts, debug log per write |
| IV. Testable without hardware | PASS | PASS | The bench models a running scope whose acquisitions change between transfers, plus arming, forcing and restoring (R11); all requirements covered by bench tests; hardware tests stay opt-in |
| V. Simple and pragmatic | PASS | PASS | No new dependencies, modules or layers: a small state in the existing worker, three driver methods, one checkbox and two labels; `WAIT`/`*OPC?` left out (R3) |
| Tech constraints | PASS | PASS | Unchanged stack |

No violations; Complexity Tracking not needed.

Specs 001 (FR-018) and 002 (FR-020) stay valid for normal mode; this spec defines the only
exception, as the constitution requires.

## Project Structure

### Documentation (this feature)

```text
specs/003-synchronized-capture/
├── plan.md              # This file
├── research.md          # Phase 0: measurements and decisions (R1–R13)
├── data-model.md        # Phase 1: capture session state, update coherence, bench fields
├── quickstart.md        # Phase 1: bench and real-scope scenarios
├── contracts/
│   ├── driver-control.md    # control allowlist, driver methods, worker signals/guarantees
│   ├── ui.md                # switch, indicators, measurement/correlation rules, close
│   └── synthetic-bench.md   # running-scope behaviour of the synthetic scope
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
src/scope_gui/
├── driver.py                # + CONTROL_COMMANDS, is_control_allowed, _write, arm,
│                            #     force_trigger, read_trigger_mode, restore_trigger_mode
├── worker.py                # + synchronized capture state machine, sync_changed,
│                            #     set_synchronized, set_capture_paused, restore on off/
│                            #     disconnect/shutdown, link-lost message
├── analysis.py              # + MeasurementSpec.channels
└── ui/
    ├── main_window.py       # + wiring, sync indicator, mixed-trigger label, coherence per
    │                        #     update, pause -> worker, longer close grace while on
    ├── side_panel.py        # + Synchronized capture checkbox, "(synchronized)" trigger text
    ├── measurements_panel.py# + process(..., coherent), coherence log
    └── histogram_panel.py   # + correlation drops mixed cross-channel pairs

tests/
├── synthetic_scope.py       # + trigger modes, ARM/FRTR/TRMD, time-based acquisitions
├── bench.py                 # starts the synthetic scope in Auto
├── check_log.py             # + control commands listed and checked separately
├── fakes.py                 # + control commands accepted (no reply)
├── unit/
│   ├── test_driver_control.py   # NEW allowlist + driver methods
│   └── test_check_log.py        # + control commands
├── integration/
│   ├── test_sync_worker.py      # NEW worker state machine on the bench
│   ├── test_sync_ui.py          # NEW switch, indicators, close/disconnect restore
│   ├── test_mixed_triggers.py   # NEW warning, measurement and correlation skipping
│   └── test_bench_live.py       # updated for the running bench model
└── hardware/
    └── test_real_scope.py   # + synchronized capture on/off restores the mode, coherent reads
```

**Structure Decision**: Same single package. Control lives in the existing driver and worker
(no new module); UI changes extend the existing panels.

## Complexity Tracking

Not applicable: the Constitution Check has no violations.
