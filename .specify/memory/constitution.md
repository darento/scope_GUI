# Scope GUI Constitution

## Core Principles

### I. Hardware Behind a Driver Layer

All communication with the oscilloscope MUST go through a single driver interface (e.g. a
`ScopeDriver` protocol). Rules:

- GUI code MUST NOT import `pyvisa` or build/send raw remote-command strings; only driver
  implementations may do so.
- The application ships exactly one driver: the real one (VXI-11 via pyvisa + pyvisa-py). It
  MUST always show what the physical scope is acquiring; there is no simulated or demo mode.
- Instrument-specific command syntax (LeCroy remote commands) MUST live only inside the driver.

Rationale: the GUI exists to mirror the real instrument; isolating I/O in one place contains
model/firmware quirks and lets tests substitute a fake instrument (Principle IV).

### II. Responsive UI (Never Block the GUI Thread)

The Qt GUI thread MUST stay responsive at all times. Rules:

- Instrument I/O, waveform transfers, and large file writes MUST NOT run on the GUI thread; they
  run in worker threads (`QThread`/worker objects or `QThreadPool`) and report back via Qt
  signals.
- Every instrument operation MUST have a finite timeout.
- Connection loss or instrument errors MUST be reported in the UI (status bar/indicator) and MUST
  NOT freeze or crash the application.
- Widgets MUST NOT be touched from worker threads; only signal/slot hand-off is allowed.

Rationale: a frozen window during a slow waveform transfer or a dropped LAN link is the most
common failure of instrument GUIs.

### III. Safe by Default

The application MUST NOT change the scope's state unless the user explicitly asks it to. Rules:

- Connecting, reconnecting, startup, and passive monitoring/polling MUST issue read-only
  queries only.
- Any command that changes scope state (settings, trigger, acquisition mode, setup recall) MUST
  be the direct result of an explicit user action.
- Destructive or hard-to-reverse operations (`*RST`, setup recall/overwrite, deleting files on
  the scope, calibration) MUST require a confirmation dialog.
- Every state-changing command sent to the instrument MUST be logged.

Rationale: the scope is shared lab equipment; an unattended or accidental write can destroy
someone else's carefully prepared setup.

### IV. Testable Without Hardware

Every feature MUST be verifiable with no oscilloscope connected. Rules:

- Each feature MUST ship with pytest tests that run against a fake instrument. Fakes live
  only under `tests/` and MUST NOT be reachable from the application.
- The default test run (`uv run pytest`) MUST pass on a machine with no scope and no NI-VISA.
- Tests that need real hardware MUST be marked (e.g. `@pytest.mark.hardware`) and skipped by
  default.
- GUI behaviour SHOULD be tested with `pytest-qt` where practical; driver logic MUST be tested
  directly.

Rationale: the scope is not always available or free to use; tests must not depend on bench
access.

### V. Simple and Pragmatic

This is an internal lab tool for a small team, targeting one instrument family. Rules:

- Build only what a current spec requires (YAGNI); no speculative plugin systems, multi-vendor
  abstractions, or configuration frameworks.
- The driver layer (Principle I) is the sanctioned abstraction; any additional layer or pattern
  MUST be justified in the plan's Complexity Tracking.
- New third-party dependencies MUST be justified in the plan; prefer the standard library,
  PySide6, and the established stack.
- Clear, readable code is preferred over clever or generic code.

Rationale: a small, understandable codebase is easier to maintain by engineers whose main job is
not software.

## Technology Stack & Constraints

- **Language/runtime**: Python 3.13 (64-bit CPython).
- **GUI**: PySide6 (Qt for Python, LGPL). PyQt MUST NOT be mixed in.
- **Instrument I/O**: `pyvisa` with the `pyvisa-py` backend over VXI-11 (LXI). The application
  MUST NOT require NI-VISA or other vendor VISA installs.
- **Environment & dependencies**: managed with `uv`. Dependencies are declared in
  `pyproject.toml`; `uv.lock` MUST be committed; commands run via `uv run ...`.
- **Platform**: Windows 11 is the primary target; code SHOULD avoid gratuitous OS-specific
  behaviour.
- **Target instrument**: LeCroy WaveRunner 610Zi (firmware 9.1.0). The instrument address
  (currently `TCPIP0::192.168.0.9::inst0::INSTR`) MUST be configurable, never hard-coded in logic.

## Development Workflow & Quality Gates

- Work follows the Spec Kit flow: `/speckit-specify` → (`/speckit-clarify`) → `/speckit-plan` →
  `/speckit-tasks` → `/speckit-implement`, on a feature branch per spec (`NNN-short-name`).
- Each plan MUST include a Constitution Check against Principles I–V before design and again
  after design; violations MUST be justified in Complexity Tracking or removed.
- Before merging to `main`: `uv run pytest` MUST pass (hardware tests excluded), and code SHOULD
  pass `ruff check` and `ruff format`.
- Manual verification against the real scope SHOULD be done for features that change instrument
  communication, and noted in the feature's task list.

## Governance

This constitution supersedes other project practices and conventions. Where a spec, plan, or
task conflicts with it, the constitution wins until it is amended.

- **Amendments** are made through `/speckit-constitution`, recorded in this file with an updated
  version and Last Amended date, and committed with a message describing the change.
- **Versioning** follows semantic versioning: MAJOR for removing or redefining a principle,
  MINOR for adding a principle/section or materially expanding guidance, PATCH for
  clarifications and wording.
- **Compliance** is checked in every plan's Constitution Check and during review before merge;
  unjustified complexity or principle violations block the merge.

**Version**: 2.0.0 | **Ratified**: 2026-10-23 | **Last Amended**: 2026-10-23
