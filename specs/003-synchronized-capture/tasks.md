---

description: "Task list for 003-synchronized-capture"
---

# Tasks: Synchronized Capture

**Input**: Design documents from `/specs/003-synchronized-capture/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/driver-control.md,
contracts/ui.md, contracts/synthetic-bench.md, quickstart.md

**Tests**: Included — required by Constitution Principle IV (every feature ships pytest tests
that run without hardware; hardware tests marked `@pytest.mark.hardware`) and listed in plan.md.
Write each story's tests first and see them fail.

**Organization**: Tasks are grouped by user story (US1 See all channels of one trigger, US2 Know
when the display mixes triggers, US3 Reproduce it without the scope).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US3)
- Single project: `src/scope_gui/`, `tests/` at repository root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the baseline; no new dependencies

- [ ] T001 Run `uv run pytest` (expect 441 passed, 3 deselected) and `uv run ruff check` /
  `uv run ruff format --check` on the branch before any change; do not add dependencies to
  `pyproject.toml`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The driver's control commands and a bench that behaves like a running scope; every
story is tested on them

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T002 [P] Write `tests/unit/test_driver_control.py` (contracts/driver-control.md, driver
  guarantees 1–4) against `FakeVisaResource`: `is_control_allowed` accepts exactly `ARM`,
  `FRTR`, `TRMD AUTO`, `TRMD NORM`, `TRMD SINGLE`, `TRMD STOP` and refuses e.g. `TRMD`,
  `TRMD FOO`, `arm`, `ARM ;*RST`, `C1:VDIV 1`, `*RST`, every read-only query; no command is
  accepted by both `is_allowed` and `is_control_allowed`; `arm()`/`force_trigger()` write
  `ARM`/`FRTR` and read nothing; `read_trigger_mode()` parses `TRMD AUTO`, `TRIG_MODE NORM`
  and bare `STOP` (CHDR SHORT/LONG/OFF); `restore_trigger_mode(TriggerMode.NORM)` writes
  `TRMD NORM`, then queries `TRMD?`, logs `trigger mode restored to Normal` at INFO, and raises
  `ScopeProtocolError` when `TRMD?` then answers another mode; a write after disconnect raises
  `ScopeError`; a socket reset on write raises `ScopeLost`; a monkeypatched `_write` with a
  non-control command raises `CommandNotAllowed` before reaching the resource
- [ ] T003 Implement in `src/scope_gui/driver.py`: `CONTROL_COMMANDS` (fullmatch `ARM`, `FRTR`,
  `TRMD (AUTO|NORM|SINGLE|STOP)`), `is_control_allowed`, `_write(command)` (check control
  allowlist and connection, `log.debug("write %s", command)`, `resource.write`, map
  `VisaIOError`/`OSError` like `_query`), `arm`, `force_trigger`, `read_trigger_mode`
  (`TRMD?` → `TriggerMode[...]`), `restore_trigger_mode(mode)` (write `TRMD <name>` with the
  enum *name*, confirm with `TRMD?`); update the module docstring (read-only allowlist plus
  the acquisition-control exception of constitution v2.1.0 III); make T002 pass
- [ ] T004 [P] Extend `tests/fakes.py` `FakeVisaResource` so allowlisted control writes are
  recorded in `sent` and leave no pending reply (a later read times out like the scope), and
  `TRMD <mode>` changes its `TRMD?` reply
- [ ] T005 [P] Write `tests/integration/test_synthetic_running.py` (contracts/synthetic-bench.md
  1–6) on a `SyntheticScope` used directly (write/read_raw): in `AUTO`/`NORM` two `WF? ALL`
  transfers more than `1/rate_hz` apart return different trigger times and reads within one
  period return the same one; `ARM` → `TRMD?` answers `SINGLE` until the next trigger is due,
  then `STOP`, and all four channels then share one trigger time that does not change while
  stopped; `triggers=False` → stays `SINGLE` until `FRTR`, then `STOP` with a new trigger time;
  `FRTR` while `STOP` changes nothing; `TRMD NORM` → running again; `TRMD SINGLE` arms like
  `ARM`; control commands appear in `sent` and `controls`; `on_demand=True` reproduces the 002
  behaviour (new acquisition per `WF? DESC`, same one for the following `WF? ALL`)
- [ ] T006 Implement the running model in `tests/synthetic_scope.py` per contract and data-model
  (`trigger_mode` set by `TRMD <mode>`, default `"NORM"`; `triggers=True`; `on_demand=False`;
  time-based newest acquisition generated lazily with skipped triggers only advancing the
  trigger time; `ARM`/`TRMD SINGLE` arm with `armed_due` = next trigger time; `FRTR`; `STOP`
  holds; `controls` list); keep `acquisitions` counting generated acquisitions; update the
  module docstring; make T005 pass
- [ ] T007 Move the existing bench tests onto the right model: `bench` fixture in
  `tests/integration/test_bench_live.py` gets an `on_demand=True` default for the 002 analysis
  tests (each acquisition measured once, pause, settings change, export, …);
  `test_channels_of_one_acquisition_share_the_trigger_time` reads from a stopped bench;
  `tests/integration/test_bench_accuracy.py` and `tests/integration/test_check_coherence.py`
  pass `on_demand=True` where they rely on one acquisition per descriptor read; run
  `uv run pytest` until all previous tests pass again
- [ ] T008 [P] Add `MeasurementSpec.channels` (`{source}`, or `{source, source2}` for Δt) in
  `src/scope_gui/analysis.py` with a test in `tests/unit/test_analysis.py` (Δt C1 → C2 has two,
  Δt C2 → C2 one, Amplitude C3 one)

**Checkpoint**: control commands exist only in the driver and are refused otherwise; the bench
reproduces mixed reads; all 002 tests still pass.

---

## Phase 3: User Story 1 - See all channels of one trigger (Priority: P1) 🎯 MVP

**Goal**: An opt-in switch makes every update show all enabled channels from one trigger, and
switching it off (or disconnecting, closing) restores the scope's trigger mode.

**Independent Test**: on a running bench, switch the mode on: every displayed update has one
trigger time for all channels; switch it off: the bench's trigger mode is the one before.

### Tests for User Story 1

> Write these first and ensure they fail before implementation.

- [ ] T009 [P] [US1] Write `tests/integration/test_sync_worker.py` (contracts/driver-control.md
  worker guarantees 1–10) with `AcquisitionWorker` + real `ScopeDriver` + running
  `SyntheticScope` (recorder consumes waveforms like the GUI): mode off after connect and
  `set_synchronized(True)` ignored when not connected; on: `TRMD?` read, `sync_changed(True,
  "")`, every emitted set has one trigger time across channels (≥ 10 sets at a trigger rate
  faster than the read time); `rate_updated` reports synchronized updates (FR-012); the next
  `ARM` is sent right after a set is emitted, but no channel of the next set is read before
  `waveforms_consumed()`; no `ARM` while `set_capture_paused(True)`; each cycle transfers at
  most one channel (record the bench's `WF? ALL` per cycle); remembered Auto + `triggers=False`: exactly one `FRTR` per arm,
  sent ≥ 0.5 s after `ARM`; remembered Normal/Stopped: never `FRTR`, status
  `WAITING_FOR_TRIGGER` after 1 s armed; emitted status `trigger_mode` = remembered mode while
  on; off: `TRMD <mode>` sent and the bench back in that mode (from AUTO, NORM, SINGLE, STOP);
  `close_connection` and `shutdown` while on restore before closing; switch off while armed in
  Normal without triggers restores within 2 s; bench mode set to `AUTO` externally while armed
  and, separately, between two updates (caught by the `TRMD?` before `ARM`) →
  `sync_changed(False, "Trigger mode changed on the scope - synchronized capture switched
  off")` and no `TRMD` sent; link lost while on (bench `reset`) → LOST message ends with `The
  scope may be left stopped - set its trigger mode back to Auto.`, and the same sentence after a
  conflict (foreign replies for `CONFLICT_AFTER` cycles); written commands while on
  ⊆ {`ARM`, `FRTR`, `TRMD <remembered>`}; with the mode never switched on, `controls` is empty;
  the INFO log has `synchronized capture on (was Auto)` and `synchronized capture off
  (switched off): N acquisitions armed, M triggers forced`
- [ ] T010 [P] [US1] Write `tests/integration/test_sync_ui.py` (contracts/ui.md) with the bench
  window: checkbox **Synchronized capture** disabled when not connected, unchecked at start and
  after disconnect/reconnect; ticking shows the amber label "Driving the scope: synchronized
  capture" and `Trigger: Auto (synchronized)`; unticking hides them and restores the bench
  mode; a worker-initiated end unchecks the box and shows its message in the status bar; no
  "Scope settings changed during this run" note while the mode runs with measurements
  collecting; Pause stops arming (no new `ARM` while paused), Resume re-arms; closing the window
  while on restores the bench mode (close waits up to 3 s)

### Implementation for User Story 1

- [ ] T011 [US1] Implement synchronized capture in `src/scope_gui/worker.py` per data-model
  state transitions: `sync_changed = Signal(bool, str)`; `set_synchronized` slot; thread-safe
  `set_capture_paused` (`threading.Event`); session fields (`restore_mode`, phase
  `IDLE`/`ARMED`/`READING`, `pending`, `armed_at`, `forced`, counts) reset on connect; in
  `_cycle`, when on: `IDLE` + not paused → `read_trigger_mode()` (expect `STOP`; `AUTO`/`NORM`
  → external change), `arm()`, `read_status()` (its `TRMD?` is the first poll) → `ARMED`;
  `ARMED` → `read_trigger_mode()` every `SYNC_POLL_MS = 10`: `SINGLE` + remembered Auto + ≥
  `FORCE_AFTER_S = 0.5` s + not forced → `force_trigger()`; `AUTO`/`NORM` → end without
  restore (FR-008); `STOP` → wait for `waveforms_consumed()` → `READING`: one enabled channel
  per cycle (R8); after the last: log a warning if the trigger times differ, emit status (with
  `trigger_mode` = remembered mode, `acq_state` per data-model) and waveforms, append to
  `_acq_times` for the rate (FR-012) → `IDLE` (arms at once, R3); `close_connection`,
  `shutdown` and switching off restore first (failed restore → message naming the mode);
  `_handle_failure`/conflict paths append the "may be left stopped" sentence when on; INFO logs
  for on/off/restore with counts (FR-007); the mode-off loop unchanged; make T009 pass
- [ ] T012 [P] [US1] Add the **Synchronized capture** checkbox (with the contract tooltip) to the
  Acquisition group in `src/scope_gui/ui/side_panel.py`, a `synchronized_toggled` signal,
  `set_synchronized(on)` (checks without re-emitting) and the `(synchronized)` suffix on the
  trigger line while on; enabled only while connected
- [ ] T013 [US1] Wire it in `src/scope_gui/ui/main_window.py`: `request_synchronized` queued to
  `worker.set_synchronized`; `worker.sync_changed` → checkbox, amber permanent status-bar label,
  status-bar message; pause → `worker.set_capture_paused`; reset the switch on disconnect/lost;
  `closeEvent` waits `SYNC_SHUTDOWN_GRACE_MS = 3000` while the mode is on (else 1000) before
  aborting; make T010 pass
- [ ] T014 [US1] Add to `tests/hardware/test_real_scope.py` (marked hardware; arms the scope and
  restores its mode): with the worker on the real scope, switch on for 10 s → every update has
  one trigger time, then off → `TRMD?` equals the mode before; repeat starting from Normal only
  if the scope was in Normal (never change the user's mode otherwise); no written command
  outside {`ARM`, `FRTR`, `TRMD <mode before>`}

**Checkpoint**: US1 works on the bench end to end and is the MVP.

---

## Phase 4: User Story 2 - Know when the display mixes triggers (Priority: P2)

**Goal**: In normal mode, mixed updates are flagged and cross-channel values from them are not
accumulated.

**Independent Test**: running bench, mode off: the warning appears; Δt C1 → C2 counts those
updates as missed while Amplitude C1 keeps counting; with the bench stopped the warning goes.

### Tests for User Story 2

- [ ] T015 [P] [US2] Write `tests/integration/test_mixed_triggers.py`: with synthetic waveform
  dicts (same and different `trigger_time` per channel) on `MeasurementsPanel.process(...,
  coherent=False)`: Δt C1 → C2 records a miss, Δt C2 → C2, Amplitude C1 and Frequency C1 record
  values; coherence log aligned with the trigger log and cleared by **Clear**; correlation view:
  Δt C1 → C2 vs Amplitude C1 and Amplitude C1 vs Amplitude C2 drop mixed acquisitions, Amplitude
  C1 vs Frequency C1 keeps them, N counts kept pairs; with the bench window (running bench, mode
  off): the label "Channels from different triggers - switch Synchronized capture on" appears
  within one update, is hidden after switching the mode on, when the bench is stopped and after
  disconnect; with one channel enabled it never appears

### Implementation for User Story 2

- [ ] T016 [P] [US2] `src/scope_gui/ui/measurements_panel.py`: `process(waveforms, gate=None,
  coherent=True)` records NaN for specs with `len(spec.channels) > 1` when not coherent;
  per-acquisition coherence log (same capacity and alignment as `trigger_log`), cleared with the
  statistics, exposed for the histogram panel
- [ ] T017 [P] [US2] `src/scope_gui/ui/histogram_panel.py`: `_draw_correlation` drops pairs from
  mixed acquisitions when the two specs' channels together exceed one (R10)
- [ ] T018 [US2] `src/scope_gui/ui/main_window.py`: coherence of each displayed update (all
  `trigger_time` equal), amber permanent mixed-trigger label shown/hidden per contracts/ui.md,
  `coherent` passed to `process` (always true while the mode is on); make T015 pass

**Checkpoint**: US1 and US2 both work independently on the bench.

---

## Phase 5: User Story 3 - Reproduce it without the scope (Priority: P3)

**Goal**: The bench launcher shows the original problem and its fix with no hardware.

**Independent Test**: `uv run python tests/bench.py` shows the mixed warning; ticking the mode
removes it.

- [ ] T019 [P] [US3] Extend `tests/integration/test_bench_live.py`: `build_window` gives a
  running synthetic scope in `AUTO` (not `on_demand`); connected launcher window shows the
  mixed-trigger label; ticking Synchronized capture hides it, the bench's `controls` contain
  only `ARM`/`FRTR`/`TRMD AUTO`, and unticking leaves the bench in `AUTO`
- [ ] T020 [US3] `tests/bench.py`: create the `SyntheticScope` in `AUTO` with the running model;
  mention the switch in the launcher's docstring/help; make T019 pass
- [ ] T021 [P] [US3] `tests/integration/test_check_coherence.py`: on a running bench with a
  trigger rate faster than the reads, `check_coherence.main` flags reads as different triggers
  and returns 1 (no monkeypatching needed any more); keep the stopped-bench case returning 0

**Checkpoint**: all three stories done.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T022 [P] `tests/check_log.py` + `tests/unit/test_check_log.py`: parse `write <command>` log
  lines; list control commands in their own block; FAIL on any command in neither allowlist;
  PASS line states the number of control commands (0 for a read-only session, SC-004)
- [ ] T023 [P] `README.md`: replace "strictly read-only" with read-only by default plus the
  opt-in Synchronized capture (what it writes, that it restores the mode, the front-panel Stop
  limitation); bench section: the bench now runs like the scope; link
  `specs/003-synchronized-capture/quickstart.md`
- [ ] T024 Full `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`; measure on the
  bench the update rate with the mode on vs off at 200k points and record it in
  `specs/003-synchronized-capture/checklists/validation.md` (no checkbox lines in that file)
- [ ] T025 Real-scope validation per quickstart.md R1–R9 and `uv run pytest -m hardware` (needs
  the scope and a person; record results, including SC-001 to SC-004, in
  `specs/003-synchronized-capture/checklists/validation.md`)
- [ ] T026 After T025: set `specs/003-synchronized-capture/spec.md` Status to Implemented,
  amending any success criterion the measurements contradict

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none
- **Foundational (Phase 2)**: after Setup; blocks all stories (driver control + running bench)
- **US1 (Phase 3)**: after Foundational
- **US2 (Phase 4)**: after Foundational; T018 also touches `main_window.py` after T013, so run
  it after US1 when working alone
- **US3 (Phase 5)**: after Foundational; T019's switch assertions need US1
- **Polish (Phase 6)**: after the stories it documents; T025/T026 need the scope

### Within Each Story

- Tests first, failing; then implementation until they pass
- Worker (T011) before window wiring (T013); panels (T016, T017) before the window (T018)

### Parallel Opportunities

- Phase 2: T002, T004, T005, T008 in parallel (different files); T003 after T002, T006 after
  T005, T007 after T006
- US1: T009, T010 in parallel; T012 in parallel with T011
- US2: T015, T016, T017 in parallel
- US3: T019, T021 in parallel
- Polish: T022, T023 in parallel

---

## Parallel Example: User Story 1

```text
Task: "T009 Write tests/integration/test_sync_worker.py"
Task: "T010 Write tests/integration/test_sync_ui.py"
# then
Task: "T011 Implement synchronized capture in src/scope_gui/worker.py"
Task: "T012 Add the checkbox in src/scope_gui/ui/side_panel.py"
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Phases 1–2: driver control and running bench
2. Phase 3: Synchronized capture end to end on the bench
3. **Stop and validate** on the real scope (quickstart R2–R7) before US2

### Incremental Delivery

1. US1 → coherent updates on demand (fixes the reported problem)
2. US2 → users are told when the display mixes triggers
3. US3 → the launcher demonstrates both
4. Polish → log checker, README, validation

---

## Notes

- Never write a scope command outside `CONTROL_COMMANDS`; hardware tests must restore the
  user's trigger mode
- Commit after each task or logical group; never push
