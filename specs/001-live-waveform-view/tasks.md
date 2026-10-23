---

description: "Task list for 001-live-waveform-view"
---

# Tasks: Live Waveform View

**Input**: Design documents from `/specs/001-live-waveform-view/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/scope-driver.md,
contracts/ui.md, quickstart.md

**Tests**: Included — required by Constitution Principle IV (every feature ships pytest tests that
run without hardware; hardware tests marked `@pytest.mark.hardware`).

**Organization**: Tasks are grouped by user story (US1 Connect, US2 Mirror live waveforms).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2)
- Single project: `src/scope_gui/`, `tests/` at repository root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: uv project, package skeleton, test infrastructure

- [X] T001 Create `pyproject.toml`: project `scope-gui`, `requires-python = ">=3.13"`, src layout
  (hatchling build backend, package `scope_gui` in `src/`), runtime deps `PySide6`, `pyvisa`,
  `pyvisa-py`, `numpy`, `pyqtgraph`; dev dependency group `pytest`, `pytest-qt`, `ruff`; script
  `scope-gui = "scope_gui.__main__:main"`; `[tool.ruff]` line-length 100, target py313;
  `[tool.pytest.ini_options]` testpaths `tests`, marker `hardware: needs the real scope`,
  `addopts = "-m 'not hardware'"`, `qt_api = "pyside6"`
- [X] T002 Create package skeleton: `src/scope_gui/__init__.py` (`__version__ = "0.1.0"`),
  `src/scope_gui/ui/__init__.py`, and test folders `tests/unit/`, `tests/integration/`,
  `tests/hardware/`, `tests/fixtures/` (no `__init__.py`; pytest rootdir-based discovery)
- [X] T003 Pin interpreter and lock: write `.python-version` (`3.13`), run
  `uv sync --python cpython-3.13-windows-x86_64` (64-bit; the machine's default 32-bit 3.11 fails
  to build wheels), commit `uv.lock`
- [X] T004 [P] Create `tests/conftest.py`: `--scope-address` option (default `192.168.0.9`);
  fixture `scope_address`; when running with `-m hardware`, skip hardware tests with a clear
  reason if TCP port 111 on the address is unreachable within 3 s
- [X] T005 [P] Create fixture capture tool `tests/fixtures/capture_fixtures.py` (dev-only, run
  manually against the real scope, uses only allowlisted queries from
  contracts/scope-driver.md): saves `tests/fixtures/wr610zi_replies.json` (exact reply strings of
  `*IDN?`, `CHDR?`, `CFMT?`, `CORD?`, `WFSU?`, `TDIV?`, `TRDL?`, `TRMD?`, `GRID?`, and
  `Cn:TRA?`/`Cn:VDIV?`/`Cn:OFST?`/`Cn:CPL?` for n=1..4), raw `Cn:WF? DESC` replies as
  `tests/fixtures/c{n}_desc.bin`, and one full `C1:WF? ALL` reply gzipped as
  `tests/fixtures/c1_wf_all.bin.gz`; run it once and commit the fixtures

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Data types, WAVEDESC decoding, driver core with allowlist, fake instrument,
settings and logging — needed by both stories

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T006 Create `src/scope_gui/models.py` per data-model.md: enums `ConnectionState`
  (`DISCONNECTED`, `CONNECTING`, `CONNECTED`, `LOST`, `ERROR`), `InstrumentSupport`
  (`SUPPORTED`, `UNTESTED_LECROY`, `NOT_LECROY`), `TriggerMode` (`AUTO`, `NORM`, `SINGLE`,
  `STOP`), `AcqState` (`ACQUIRING`, `WAITING_FOR_TRIGGER`, `STOPPED`); frozen dataclasses
  `InstrumentIdentity`, `ChannelSettings` (`volts_per_div` "> 0"; "screen centre = −offset"),
  `AcquisitionSettings` (`time_per_div` "> 0"; "screen centre time = −trigger_delay";
  `h_divisions=10`, `v_divisions=8`), `ScopeStatus`, `WaveformDescriptor`, `Waveform`
  (`volts` float32 ndarray, `t0`, `dt`, `trigger_time`, `received_at`); constants
  `CHANNELS = ("C1","C2","C3","C4")` and `CHANNEL_COLORS` = C1 `#F5E400`, C2 `#FF5FAF`,
  C3 `#3FC8F0`, C4 `#40D040`; function `classify_support(identity)` per research R11
  (`LECROY`+`WR610ZI` → SUPPORTED, other `LECROY` → UNTESTED_LECROY, else NOT_LECROY)
- [X] T007 [P] Write `tests/unit/test_wavedesc.py`: parse the IEEE 488.2 block with and without
  the `C1:WF ALL,` header; parse `tests/fixtures/c1_desc.bin` and assert values measured in
  research R6 for the capture (COMM_TYPE byte, LOFIRST, WAVE_ARRAY_COUNT, gain, offset,
  HORIZ_INTERVAL, HORIZ_OFFSET, WAVE_SOURCE C1); decode `c1_wf_all.bin.gz` into volts with
  `volts = VERTICAL_GAIN × code − VERTICAL_OFFSET`; synthetic word (int16) and big-endian
  (HIFIRST) records; reject blocks not starting with `WAVEDESC`, template ≠ `LECROY_2_3`, or data
  length ≠ `point_count × bytes_per_sample` with `ScopeProtocolError`
- [X] T008 Implement `src/scope_gui/wavedesc.py` (pure functions, numpy only):
  `split_block(raw: bytes) -> bytes` (strip optional header up to `#`, parse `#9NNNNNNNNN`
  definite length); `parse_descriptor(payload) -> WaveformDescriptor` using LECROY_2_3 offsets —
  DESCRIPTOR_NAME@0 (16 s), TEMPLATE_NAME@16 (16 s), COMM_TYPE@32 (i16: 0 byte, 1 word),
  COMM_ORDER@34 (i16: 0 HIFIRST, 1 LOFIRST — sets endianness for all following fields),
  WAVE_DESCRIPTOR@36, USER_TEXT@40, RES_DESC1@44, TRIGTIME_ARRAY@48, RIS_TIME_ARRAY@52,
  RES_ARRAY1@56, WAVE_ARRAY_1@60 (i32 byte lengths), INSTRUMENT_NAME@76 (16 s),
  WAVE_ARRAY_COUNT@116, FIRST_VALID_PNT@124, LAST_VALID_PNT@128 (i32), VERTICAL_GAIN@156,
  VERTICAL_OFFSET@160, HORIZ_INTERVAL@176 (f32), HORIZ_OFFSET@180 (f64),
  TRIGGER_TIME@296 (f64 seconds, u8 minutes, u8 hours, u8 days, u8 months, i16 year → convert
  to absolute float seconds), WAVE_SOURCE@344 (i16 0..3 → C1..C4); verify the offsets against
  the captured fixture; `decode_waveform(raw) -> (WaveformDescriptor, volts ndarray)` with data
  starting after WAVE_DESCRIPTOR+USER_TEXT+TRIGTIME_ARRAY+RIS_TIME_ARRAY+RES_ARRAY1 bytes;
  raise `ScopeProtocolError` (defined in `src/scope_gui/errors.py`, see T009) on any mismatch
- [X] T009 Create `src/scope_gui/errors.py` with `ScopeError` and subclasses `ScopeUnreachable`,
  `ScopeBusy`, `ScopeTimeout`, `ScopeProtocolError`, `ScopeLost`, and
  `CommandNotAllowed` (raised before any non-allowlisted command reaches the wire)
- [X] T010 Implement driver core in `src/scope_gui/driver.py`: `ALLOWED_COMMANDS` as compiled
  regexes exactly matching the allowlist in contracts/scope-driver.md (`*IDN?`, `CHDR?`,
  `CFMT?`, `CORD?`, `WFSU?`, `C[1-4]:TRA?`, `C[1-4]:VDIV?`, `C[1-4]:OFST?`, `C[1-4]:CPL?`,
  `TDIV?`, `TRDL?`, `TRMD?`, `GRID?`, `C[1-4]:WF? DESC`, `C[1-4]:WF? ALL`); private `_query(cmd)`
  and `_query_raw(cmd, timeout_ms)` that check the allowlist (raise `CommandNotAllowed`), log each
  command at DEBUG, and map pyvisa errors (`VI_ERROR_TMO` → `ScopeTimeout`, lock/`VI_ERROR_RSRC_BUSY`
  → `ScopeBusy`, other → `ScopeError`); `parse_value(reply) -> str` tolerant of CHDR
  `SHORT`/`LONG`/`OFF` (take the value after the header, strip units `V`, `S`, `SAMPLE`);
  `parse_float(reply)`; constructor `ScopeDriver(resource_factory=None)` whose default factory
  opens `pyvisa.ResourceManager("@py").open_resource(address, timeout=ms)`. This is the ONLY
  module importing `pyvisa`
- [X] T011 [P] Create `tests/fakes.py` (tests only, never imported by `src/`): `FakeVisaResource`
  with `write`, `read`, `read_raw`, `query`, `clear`, `close`, `timeout`; loads replies from
  `tests/fixtures/wr610zi_replies.json` and the binary fixtures; records every command written
  in `.sent`; behaves like the real scope for unknown queries (raises a pyvisa timeout error, R4);
  knobs to simulate: unreachable, busy, timeout after N calls, changed settings, changing
  `TRIGGER_TIME`, `TRMD STOP`, channel on/off; plus `fake_factory(**knobs)` for
  `ScopeDriver(resource_factory=...)`
- [X] T012 [P] Write `tests/unit/test_driver_allowlist.py`: every allowlisted command passes; a
  sample of writes (`C1:VDIV 1`, `TRMD STOP`, `*RST`, `CFMT DEF9,WORD,BIN`, `WFSU SP,10`,
  `INR?`) raise `CommandNotAllowed` and are never written to the fake; `parse_value` handles
  `C1:VDIV 1 V`, `C1:VOLT_DIV 1 V` (LONG), `1 V` (OFF), `TDIV 5E-6 S`
- [X] T013 [P] Implement `src/scope_gui/settings.py`: `QSettings("scope_gui", "scope_gui")`
  helpers `load_last_address() -> str` (default `192.168.0.9`) and `save_last_address(str)`;
  `to_visa_resource(address)` (IP/hostname → `TCPIP0::{host}::inst0::INSTR`, full VISA strings
  unchanged, strip whitespace, reject empty); `host_of(resource)`; `log_dir()` →
  `%LOCALAPPDATA%\scope_gui\logs` (created if missing)
- [X] T014 [P] Write `tests/unit/test_settings.py`: `to_visa_resource` for IP, hostname, full
  VISA string, empty (error); `host_of`; last address round-trip using a temporary QSettings
  scope (`QSettings.setPath` to `tmp_path`)
- [X] T015 Create `src/scope_gui/__main__.py` with `setup_logging()` (root logger INFO, rotating
  file `log_dir()/scope_gui.log` 1 MB × 5 backups, format with timestamp/level/thread; DEBUG for
  `scope_gui.driver` so every command sent is recorded, FR-020) and `main()` that calls
  `setup_logging()`, creates `QApplication`, and (until US1) shows an empty `QMainWindow`

**Checkpoint**: `uv run pytest` passes (wavedesc, allowlist, settings); foundation ready

---

## Phase 3: User Story 1 - Connect to the scope (Priority: P1) 🎯 MVP

**Goal**: Enter address, connect/disconnect explicitly, see identity; clear errors within 10 s;
last address remembered.

**Independent Test**: With the scope on the network, `uv run scope-gui`, press Connect → green
"Connected" with `LECROY WR610ZI`, serial and firmware; Disconnect → "Disconnected"
(quickstart scenarios 1–3).

### Tests for User Story 1

- [X] T016 [P] [US1] Write `tests/unit/test_driver_connect.py` using `fake_factory`: `connect()`
  returns identity parsed from the `*IDN?` fixture and logs `CHDR?`/`CFMT?`/`CORD?`/`WFSU?`
  replies (warning logged when WFSU is not `SP,0,NP,0,FP,0`); unreachable host → `ScopeUnreachable`
  in < 4 s (pre-check patched); busy → `ScopeBusy`; `*IDN?` timeout → `ScopeTimeout`; `close()`
  idempotent; `recover()` calls `clear()` then `*IDN?` and returns True/False; `classify_support`
  for `LECROY,WR610ZI`, `LECROY,WAVEPRO`, `KEYSIGHT,...`
- [X] T017 [P] [US1] Write `tests/integration/test_connect_ui.py` (pytest-qt, worker driver
  injected with `fake_factory`): states DISCONNECTED → CONNECTING → CONNECTED with identity text;
  unreachable shows English error message and returns to a usable state; unsupported identity
  shows Continue/Cancel dialog (Cancel → DISCONNECTED, Continue → CONNECTED); Disconnect →
  DISCONNECTED; address saved only after a successful connect; window stays responsive (event loop
  processes a timer tick while connect is pending)

### Implementation for User Story 1

- [X] T018 [US1] Implement `ScopeDriver.connect(address)`, `close()`, `recover()` in
  `src/scope_gui/driver.py`: TCP pre-check to port 111 of `host_of(address)` with 3 s timeout
  (`ScopeUnreachable` on failure); open resource with 3000 ms timeout; `*IDN?` →
  `InstrumentIdentity` (support via `classify_support`); read and log `CHDR?`, `CFMT?`, `CORD?`,
  `WFSU?` (never write them, research R3); `close()` idempotent and safe from another thread;
  `recover()` = `resource.clear()` + `*IDN?` → bool
- [X] T019 [US1] Implement `src/scope_gui/worker.py` `AcquisitionWorker(QObject)` connection part:
  constructor takes `driver_factory` (default `ScopeDriver`); signals
  `state_changed(ConnectionState, str)`, `identity_received(InstrumentIdentity)`,
  `confirmation_needed(InstrumentIdentity)`; slots `connect_to(address)`,
  `confirm_unsupported(bool)`, `disconnect()`, `shutdown()`; when support ≠ SUPPORTED, stay in
  CONNECTING until `confirm_unsupported` (False → close + DISCONNECTED); map `ScopeError`s to
  English messages ("Instrument not reachable at …", "Instrument busy (used by another
  client) — try again", "Instrument did not respond (timeout)"); all I/O runs in the worker's
  `QThread`
- [X] T020 [P] [US1] Implement `src/scope_gui/ui/connection_bar.py` `ConnectionBar(QWidget)`:
  address `QLineEdit` (editable only when DISCONNECTED/LOST/ERROR), Connect/Disconnect button
  (shows "Cancel" while CONNECTING), status dot + text (grey Disconnected, amber Connecting,
  green Connected, red Lost/Error), identity label "MANUFACTURER MODEL · SN … · FW …";
  signals `connect_requested(str)`, `disconnect_requested()`
- [X] T021 [US1] Implement `src/scope_gui/ui/main_window.py` `MainWindow(QMainWindow)`: connection
  bar on top, placeholder central widget, status bar for messages, menu Help → "Open log folder"
  (`QDesktopServices.openUrl(log_dir())`); creates `QThread` + `AcquisitionWorker`
  (`moveToThread`), wires signals with queued connections; `QMessageBox` Continue/Cancel on
  `confirmation_needed` (text per research R11); saves address on CONNECTED; `closeEvent` per
  research R8 (request `shutdown`, wait 1 s, else `driver.close()` to abort, then
  `thread.quit(); thread.wait()`); accepts an optional `driver_factory` for tests
- [X] T022 [US1] Update `src/scope_gui/__main__.py` `main()` to create `MainWindow` with the
  address from `load_last_address()` pre-filled, then `app.exec()`
- [X] T023 [P] [US1] Write `tests/hardware/test_real_scope.py::test_identity` (marked
  `hardware`): `ScopeDriver().connect(scope_address)` returns manufacturer `LECROY`, model
  `WR610ZI`, support SUPPORTED; `close()`

**Checkpoint**: US1 works end-to-end on the real scope (quickstart 1–3) and in tests

---

## Phase 4: User Story 2 - Mirror the scope's waveforms live (Priority: P2)

**Goal**: Plot enabled channels C1–C4 live on a 10×8-division grid matching the scope (scale,
offset, timebase, trigger position, colours); follow scope changes within 2 s; pause/hide
locally; Stopped/Waiting states; stale on loss; strictly read-only.

**Independent Test**: Scope showing its calibration signal; PC view next to the scope screen
shows the same channels, positions and shapes; turning a channel off/changing V/div on the scope
is mirrored within 2 s (quickstart scenarios 4–12).

### Tests for User Story 2

- [X] T024 [P] [US2] Write `tests/unit/test_driver_status.py`: `read_status()` from fixtures
  returns `ChannelSettings` for C1–C4 (enabled flags, VDIV, OFST, CPL) and
  `AcquisitionSettings` (TDIV 5e-6, TRDL −9.2e-6, TRMD AUTO, GRID SINGLE); `read_descriptor("C1")`
  sends exactly `C1:WF? DESC`; `read_waveform("C1")` sends `C1:WF? ALL` with timeout
  `2000 + bytes/1000` ms capped at 10000 and returns volts matching wavedesc decoding
- [X] T025 [P] [US2] Write `tests/unit/test_geometry.py`: `x_range(acq)` =
  `(−TRDL − 5·TDIV, −TRDL + 5·TDIV)` equals `(−15.8e-6, 34.2e-6)` for the fixture values (matches
  `HORIZ_OFFSET`, research R6); `volts_to_div(v, ch) = (v + offset) / volts_per_div` — for C1
  (1 V/div, offset −3.01 V): 3.01 V → 0 div (screen centre), 4.01 V → +1 div; `div_to_volts`
  is its inverse; y range is ±4 div
- [X] T026 [P] [US2] Write `tests/integration/test_worker_live.py` (pytest-qt + fake): one status
  emitted per cycle (cycle ≤ 1 s); full records fetched only for enabled channels and only when
  `TRIGGER_TIME` changes; `TRMD STOP` → `AcqState.STOPPED` and no `WF? ALL` sent; `NORM` with
  unchanged trigger time > 1 s → `WAITING_FOR_TRIGGER`; settings change in fake appears in next
  status; one timeout followed by successful `recover()` keeps CONNECTED (auto-retry, spec
  clarification Q5); persistent failure → `LOST` within 5 s; `rate_updated` reflects received
  acquisitions; every command in `fake.sent` matches `ALLOWED_COMMANDS`
- [X] T027 [P] [US2] Write `tests/integration/test_live_ui.py` (pytest-qt): only enabled
  channels have visible curves, coloured per `CHANNEL_COLORS`; unchecking a channel hides only
  the PC curve and sends nothing to the fake; Pause stops curve updates while worker keeps
  emitting, Resume continues; "No channels enabled on the scope" shown when none enabled;
  multi-grid note shown when `GRID?` ≠ `SINGLE`; LOST → traces dimmed + "STALE — not live";
  status bar shows rate and last update time; channel panel shows V/div/offset/coupling text

### Implementation for User Story 2

- [X] T028 [US2] Add to `src/scope_gui/models.py`: `x_range(acq) -> (float, float)`,
  `volts_to_div(volts, ch: ChannelSettings)`, `div_to_volts(div, ch)`, `Y_RANGE_DIV = (-4, 4)`
- [X] T029 [US2] Implement `ScopeDriver.read_status()`, `read_descriptor(ch)`,
  `read_waveform(ch)` in `src/scope_gui/driver.py` using only allowlisted queries; waveform
  timeout `min(2000 + expected_bytes/1000, 10000)` ms where expected bytes come from the last
  descriptor; return `ScopeStatus`/`WaveformDescriptor`/`Waveform` (with `received_at =
  time.monotonic()`)
- [X] T030 [US2] Implement the live loop in `src/scope_gui/worker.py`: after CONNECTED, a
  `QTimer` (single-shot, re-armed; 200 ms when idle, immediate after transfers, ≤ 1 s between
  status reads) runs a cycle: `read_status()` → emit `status_updated(ScopeStatus)`; if `STOP` →
  `STOPPED`, skip transfers; else `read_descriptor(first enabled channel)` and compare
  `trigger_time`; if new, `read_waveform` for each enabled channel → emit
  `waveforms_updated(dict[str, Waveform])`; derive `WAITING_FOR_TRIGGER` (NORM/SINGLE and no new
  trigger for > 1 s); emit `rate_updated(float)` (moving average over last 5 acquisitions); on
  `ScopeTimeout`/`ScopeBusy` call `recover()` and retry; if not recovered within 5 s since the
  first failure → `LOST` with message; `disconnect()`/`shutdown()` stop the timer and close
- [X] T031 [P] [US2] Implement `src/scope_gui/ui/scope_plot.py` `ScopePlot(QWidget)` with
  pyqtgraph (`pg.setConfigOptions(antialias=False)`): black background, mouse pan/zoom disabled,
  X fixed to `x_range(acq)` in seconds (SI-prefixed axis), Y fixed to ±4 div, grid lines every
  division (10 × 8) plus dotted centre lines; one `PlotDataItem` per channel with
  `setDownsampling(auto=True, method="peak")` and `setClipToView(True)`, pen colour from
  `CHANNEL_COLORS`; data plotted as `t = t0 + i·dt` vs `volts_to_div`; trigger marker
  (vertical line at t=0, small "T" label); hover readout showing time and each visible channel's
  volts at cursor (`div_to_volts`); overlay texts: "No channels enabled on the scope",
  "Scope uses a multi-grid layout; shown here on one grid", and "STALE — not live" (with traces
  at 40 % opacity); methods `set_status(ScopeStatus)`, `set_waveforms(dict)`,
  `set_hidden(set[str])`, `set_stale(bool)`
- [X] T032 [P] [US2] Implement `src/scope_gui/ui/side_panel.py` `SidePanel(QWidget)`: per channel
  a checkbox in the channel colour (disabled + "(off)" when off at the scope) with
  "V/div · offset · coupling" text; acquisition box with time/div, trigger mode
  (Auto/Normal/Single/Stopped) and state (Acquiring / Waiting for trigger / Stopped); Pause/Resume
  toggle button; signals `hidden_changed(set[str])`, `paused_changed(bool)`
- [X] T033 [US2] Wire live view in `src/scope_gui/ui/main_window.py`: replace placeholder with
  `ScopePlot` + `SidePanel` (splitter); keep `LiveViewState` (paused, hidden_channels,
  update_rate_hz, stale) per data-model.md; drop `waveforms_updated` while paused; status bar
  "{rate:.1f} updates/s · last update HH:MM:SS"; set stale on LOST/ERROR, clear on CONNECTED;
  layout per contracts/ui.md
- [X] T034 [US2] Write `tests/hardware/test_real_scope.py::test_live_read_only` (marked
  `hardware`): snapshot all allowlisted setting replies, run the worker live for 30 s, snapshot
  again and assert identical (SC-005, FR-018); assert every command sent matched the allowlist;
  assert at least one waveform per enabled channel was received; log achieved rate

**Checkpoint**: US1 + US2 complete; quickstart scenarios 4–12 pass on the real scope

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T035 [P] Write `README.md`: purpose, requirements (uv, 64-bit Python 3.13 via uv, LAN to
  scope), `uv sync`, `uv run scope-gui`, `uv run pytest`, `uv run pytest -m hardware`, read-only
  guarantee, log location, link to `specs/001-live-waveform-view/quickstart.md`
- [X] T036 Run `uv run ruff check --fix` and `uv run ruff format`; fix remaining issues in
  `src/` and `tests/`
- [X] T037 Run `uv run pytest` over `tests/` (must pass with no scope) and
  `uv run pytest -m hardware` (`tests/hardware/`) against the real scope; fix failures
- [ ] T038 Run quickstart.md manual scenarios 1–13 on the real scope; verify channel colours
  against the scope screen and adjust `CHANNEL_COLORS` in `src/scope_gui/models.py` if they
  differ (research R10); record results in
  `specs/001-live-waveform-view/checklists/validation.md`

---

## Phase 6: Multi-client protection (found during validation, FR-021, research R13)

**Goal**: Never display a reply that belongs to another remote client; step back when another
program is polling the scope.

**Independent Test**: Unit/integration tests with a fake that hands out foreign replies; on the
real scope, run a second client while the app is live → app reports "Another program is using
the scope" and no wrong values are shown.

- [X] T039 [P] Add `ScopeReplyMismatch(ScopeProtocolError)` to `src/scope_gui/errors.py`
- [X] T040 Write `tests/unit/test_reply_validation.py`: accepted short/long headers for every
  allowlisted text query; mismatched header (e.g. `C1:VDIV 1 V` for `TDIV?`) raises
  `ScopeReplyMismatch` and triggers a device clear; `CHDR OFF` skips text validation; binary reply
  with wrong prefix or text instead of a block raises; descriptor `WAVE_SOURCE` ≠ requested channel
  raises; connect with a foreign reply raises
- [X] T041 Implement reply validation in `src/scope_gui/driver.py` per contracts/scope-driver.md
  "Reply validation": remember `CHDR` mode at connect; validate in `_query`/`_query_raw`; check
  `WAVE_SOURCE` in `read_descriptor`/`read_waveform`; flush (device clear) on mismatch
- [X] T042 Add knob `foreign_replies: int` to `tests/fakes.py` (next N queries get another
  command's reply, like a second client stealing replies) and write
  `tests/integration/test_worker_conflict.py`: a single mismatched cycle is discarded and polling
  continues; 3 consecutive mismatched cycles → `LOST` with "Another program is using the scope -
  reconnect when it has finished"; no mismatched value ever reaches `status_updated`
- [X] T043 Implement in `src/scope_gui/worker.py`: count consecutive cycles failing with
  `ScopeReplyMismatch` (`CONFLICT_AFTER = 3`), reset on a clean cycle, stop and report on reaching
  it; map `ScopeReplyMismatch` in `user_message` (also for connect)
- [X] T044 Re-run `uv run pytest` and `uv run pytest -m hardware`; on the real scope start a
  second client while the app is live and record the result in
  `specs/001-live-waveform-view/checklists/validation.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none. T005 needs the scope reachable (read-only).
- **Foundational (Phase 2)**: depends on Setup; blocks both stories. T008 depends on T007's
  fixtures (T005) and T009; T010 depends on T009; T011 depends on T005.
- **US1 (Phase 3)**: depends on Foundational.
- **US2 (Phase 4)**: depends on Foundational and on US1's worker/main window (T019, T021) —
  live view needs a connection; it is still verifiable as its own increment.
- **Polish (Phase 5)**: after US2.

### Within Each Story

- Tests are written first and fail, then implementation makes them pass.
- Driver → worker → widgets → main window wiring.

### Parallel Opportunities

- Setup: T004 ∥ T005.
- Foundational: T007 ∥ T011 ∥ T012 ∥ T013 ∥ T014 (after T006/T009 where imported).
- US1: T016 ∥ T017 ∥ T020 ∥ T023.
- US2: T024 ∥ T025 ∥ T026 ∥ T027, then T031 ∥ T032 (different files) after T028–T030.

---

## Parallel Example: User Story 2

```text
Task: "Write tests/unit/test_driver_status.py"        (T024)
Task: "Write tests/unit/test_geometry.py"             (T025)
Task: "Write tests/integration/test_worker_live.py"   (T026)
Task: "Write tests/integration/test_live_ui.py"       (T027)
# after T028–T030:
Task: "Implement src/scope_gui/ui/scope_plot.py"      (T031)
Task: "Implement src/scope_gui/ui/side_panel.py"      (T032)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 Setup → Phase 2 Foundational.
2. Phase 3 US1 → validate on the real scope (quickstart 1–3): connection, identity, errors.

### Incremental Delivery

1. MVP (US1) → commit.
2. US2 live mirror → validate quickstart 4–12 → commit.
3. Polish → full test run + manual validation 1–13.

---

## Notes

- Never send a command outside the allowlist; the allowlist test (T012) and hardware test
  (T034) guard FR-018.
- No simulated mode anywhere; `tests/fakes.py` is test-only (Constitution I/IV).
- Commit after each task group; never push.
