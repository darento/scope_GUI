# Research: Live Waveform View

**Feature**: 001-live-waveform-view | **Date**: 2026-10-23

All findings marked *(measured)* come from read-only queries against the lab scope
(LeCroy WR610Zi, fw 9.1.0, `TCPIP0::192.168.0.9::inst0::INSTR`) over the USB-GbE adapter, using
pyvisa + pyvisa-py on Windows 11. No setting was written to the scope during research.

## R1. Transport and VISA backend

- **Decision**: VXI-11 via `pyvisa` with the `pyvisa-py` backend (`ResourceManager("@py")`).
- **Rationale**: Works today with no vendor install *(measured: `*IDN?` → `LECROY,WR610ZI,
  LCRY3201N55990,9.1.0`)*; required by the constitution (no NI-VISA). Port 111 (portmapper) and
  80 are open; VICP (1861) and raw socket (5025) are closed, so VXI-11 is the only option.
- **Alternatives**: NI-VISA (rejected: vendor install); LeCroy VICP / ActiveDSO (rejected: port
  closed, Windows COM dependency); raw socket (not available).

## R2. Waveform transfer throughput (drives SC-002)

*(measured)*

| Item | Value |
|------|-------|
| Current record length | 500,002 points/channel (5 µs/div × 10 div at 10 GS/s) |
| Data format (`CFMT?`) | `DEF9,BYTE,BIN` → 1 byte/sample, ~500 KB per channel |
| `Cn:WF? ALL` time | ~200–220 ms per channel |
| Effective throughput | ~2.2 MB/s, independent of pyvisa `chunk_size` (20 KB … 16 MB) |
| 3 channels, full resolution | ~1.5 full refreshes/s |
| `Cn:WF? DESC` (descriptor only, 346 B) | ~4 ms |
| Simple setting query (`C1:VDIV?`) | ~2 ms |
| Text inspect (`Cn:INSP? '...'`) | ~90–140 ms (slow, avoid in the loop) |

- **Decision**: Transfer full-resolution records with `Cn:WF? ALL`, only for channels that are on
  and only when the acquisition is new (R5). Show the achieved refresh rate in the UI.
- **Rationale**: The bottleneck is the scope's own readout (~2.2 MB/s), not the PC or pyvisa.
  At the spec's reference load (≤100k points/channel → ~100 KB) a channel takes ~45 ms, so 4
  channels refresh at ~5 Hz, meeting SC-002. At the scope's current 500k points the rate drops
  to ~1.5 Hz for 3 channels; the spec explicitly allows this ("update rate may drop, and the
  actual update rate is shown").
- **Alternatives**:
  - `WFSU SP,n` sparsing (faster, ~1/n data). **Rejected for this feature**: it is a write that
    changes the remote-interface setup shared with other clients, violating FR-018 /
    Principle III. Candidate for a later, explicitly user-enabled "fast preview" with restore.
  - Changing `CFMT` to WORD (better resolution, 2× data) — rejected: write + slower.
  - Reading via VBS automation (`VBS? '...DataArray'`) — rejected: text, far slower.

## R3. Respecting the scope's current communication format (read-only)

*(measured)* `CHDR SHORT`, `CFMT DEF9,BYTE,BIN`, `CORD LO`, `WFSU SP,0,NP,0,FP,0,SN,0`.

- **Decision**: Never write `CHDR`, `CFMT`, `CORD` or `WFSU`. On connect, read them; parse every
  response tolerant of header mode (`SHORT`/`LONG`/`OFF`). Decode waveform data using the
  descriptor's own `COMM_TYPE` (byte/word) and `COMM_ORDER` (LOFIRST/HIFIRST), so any format
  another client left configured is handled. If `WFSU` shows sparsing/partial transfer (`SP≠0`,
  `NP≠0`, `FP≠0`), still display it correctly (the descriptor reflects it) and log a note.
- **Rationale**: FR-018 / Principle III forbid changing scope state; these are persistent
  settings shared with other remote users.

## R4. Error behaviour of the instrument

*(measured)* An unrecognised query (e.g. an invalid `INSP?` field) produces **no response**; the
read simply times out. After a device clear (`viClear`), the session works normally again.

- **Decision**: The driver sends only queries from a fixed allowlist (see
  [contracts/scope-driver.md](contracts/scope-driver.md)), each verified against this scope. On a
  read timeout the driver performs one device clear and one `*IDN?` health check; if that also
  fails, the connection is declared **Lost**.
- **Rationale**: Distinguishes "slow/odd reply" from "link down" and keeps detection within the
  5 s budget (FR-007).

## R5. Detecting new acquisitions and trigger state

*(measured)* `TRIGGER_TIME` in the waveform descriptor changes on every acquisition
(e.g. `15:54:54.381…`, `15:54:54.816…`). `TRMD?` returns `AUTO` / `NORM` / `SINGLE` / `STOP`.

- **Decision**: Each cycle, read `Cn:WF? DESC` (~4 ms) for one enabled channel and compare the
  binary `TRIGGER_TIME` with the last one received. Only if it changed, transfer full records
  for all enabled channels. Derived states:
  - `TRMD STOP` → **Stopped** (keep last waveform, no transfers).
  - `TRMD NORM`/`SINGLE` and trigger time unchanged for > 1 s → **Waiting for trigger**.
  - Otherwise → **Acquiring** (Auto/Normal/Single shown as reported).
- **Rationale**: Avoids re-downloading identical data (big win when stopped or slow triggers);
  uses only read-only queries. `INR?` was rejected because reading it **clears** the status
  register, a side effect on shared state.
- **Alternatives**: `INSP? 'TRIGGER_TIME'` (text, ~137 ms — too slow); `INR?` (destructive read).

## R6. Mapping to the scope's screen (FR-010, SC-006)

*(measured, C1)* `VDIV 1 V`, `OFST -3.01 V`, `VERTICAL_OFFSET -3.01`, `VERTICAL_GAIN 0.0332`,
`TDIV 5 µs`, `TRDL -9.2 µs`, `HORIZ_INTERVAL 1e-10 s`, `HORIZ_OFFSET -15.8 µs`,
500,002 points → record spans exactly 10 divisions (50 µs).

- **Decision**:
  - Sample value: `volts[i] = VERTICAL_GAIN × code[i] − VERTICAL_OFFSET`;
    time: `t[i] = HORIZ_OFFSET + i × HORIZ_INTERVAL` (seconds, relative to trigger).
  - Grid: **10 horizontal × 8 vertical divisions** (WaveRunner Zi graticule; `GRID SINGLE`).
  - X range: `[−TRDL − 5·TDIV, −TRDL + 5·TDIV]` — checked: −(−9.2) − 25 = −15.8 µs = `HORIZ_OFFSET`.
  - Each channel is drawn in **divisions** on a shared 8-div grid:
    `div = (volts + OFST) / VDIV` (screen centre = 0 div ⇒ `−OFST` volts), so channels with
    different V/div overlay exactly as on the scope. Hover/cursor readout converts back to volts
    per channel.
  - Trigger position marker at `t = 0`.
- **Rationale**: Matches the scope's own geometry independent of each channel's scale; verified
  numerically with the probe values above.
- **Note**: only `GRID SINGLE` is mirrored in this feature; for other grid modes all channels are
  drawn on one grid and the UI shows a "scope uses multi-grid layout" note (clarified in spec).

## R7. Plotting library

- **Decision**: `pyqtgraph` (PySide6 binding) with `setDownsampling(auto=True, mode="peak")` and
  `setClipToView(True)`.
- **Rationale**: Draws 500k+ points per curve at interactive rates; peak-mode downsampling keeps
  the visible shape faithful (spec assumption on reduced resolution). Pure Python, MIT, works
  with PySide6. New dependency justified per Principle V.
- **Alternatives**: Qt Charts (`PySide6.QtCharts`) — rejected: slow beyond ~100k points; matplotlib
  embedded — rejected: too slow for live updates.

## R8. Threading and connection lifecycle

- **Decision**: One `QThread` owning a worker `QObject` that owns the driver/VISA session; all I/O
  happens there. Worker emits Qt signals (`connected`, `status`, `waveforms`, `error`, `lost`,
  `rate`). GUI sends requests via queued signals (connect, disconnect, stop). A fast pre-check
  (TCP connect to port 111 with a 3 s timeout) runs before opening VXI-11 so unreachable
  addresses fail quickly (FR-006). I/O timeout: 3 s for queries; for waveform reads
  `2 s + bytes / 1 MB/s`, capped at 10 s.
- **Shutdown**: on Disconnect or window close, the worker is asked to stop at the next safe
  point; if it does not finish within 1 s (e.g. mid-transfer), the GUI closes the VISA session to
  abort the pending read, then waits for the thread.
- **Rationale**: Principle II; keeps GUI responsive (SC-003) and detection within 5 s.

## R9. Persistence and logging

- **Decision**: Last address in `QSettings` (Windows registry, per user). Logging via the stdlib
  `logging` module to a rotating file in `%LOCALAPPDATA%\scope_gui\logs\scope_gui.log`; a
  "Help → Open log folder" action exposes it (FR-020). Connection events and errors at
  INFO/WARNING; every command sent only with `SCOPE_GUI_DEBUG=1` (measured ~250 lines/s while
  live, which would rotate away the history within minutes). Rotation 5 MB × 5.
- **Rationale**: Zero extra dependencies; satisfies FR-001 and FR-020.

## R10. Channel colours

- **Decision**: Fixed MAUI default palette: C1 yellow `#F5E400`, C2 pink `#FF5FAF`,
  C3 cyan `#3FC8F0`, C4 green `#40D040`, on a black plot background like the scope.
- **Rationale**: The scope does not expose trace colours over the remote interface in a
  documented way; the defaults match the WaveRunner Zi screen. To verify visually at
  implementation time against the real scope.

## R11. Supported-instrument check (FR-004)

- **Decision**: `*IDN?` manufacturer `LECROY` and model `WR610ZI` → supported. Other `LECROY`
  models → warning "untested model, continue?". Non-LeCroy → warning "not a LeCroy oscilloscope,
  continue?". Both warnings allow continue/cancel.

## R12. Tooling

- **Decision**: `uv` project with `pyproject.toml` + `uv.lock`; runtime deps `PySide6`, `pyvisa`,
  `pyvisa-py`, `numpy`, `pyqtgraph`; dev deps `pytest`, `pytest-qt`, `ruff`. Entry point
  `scope-gui` (`uv run scope-gui`). Tests use a fake VISA resource (in `tests/` only) that replays
  real responses captured from this scope (descriptor bytes, setting replies) as fixtures.
- **Rationale**: Constitution technology constraints and Principle IV.

## R13. Simultaneous remote clients (found during validation)

*(measured, 2026-10-23)* With the app polling and a second client connecting, the second client
got `*IDN?` answered but its next `CHDR?` timed out, and the app logged "no binary block in
reply": **the scope serves one reply queue shared by all VXI-11 links**, so replies go to
whichever client reads first. A VXI-11 exclusive lock (`viLock`, pyvisa-py sends
`device_lock`) is accepted instantly but **not enforced**: a second link was still served while
the lock was held.

- **Decision**: Validate every reply against its query (FR-021): text replies must carry the
  query's header (short or long form, e.g. `TDIV`/`TIME_DIV`) when `CHDR` is not `OFF`; binary
  replies must start with `Cn:WF DESC,`/`Cn:WF ALL,` (or `Cn:WAVEFORM …`) and their descriptor's
  `WAVE_SOURCE` must equal the requested channel. A mismatch raises `ScopeReplyMismatch`, the
  driver flushes the queue (device clear) and the worker discards the cycle. After 3
  consecutive mismatched cycles the worker stops polling and reports "Another program is using
  the scope - reconnect when it has finished" (traces stale).
- **Rationale**: A stolen reply can be well-formed (e.g. `C1:VDIV 1 V` returned for `TDIV?`)
  and would otherwise silently show wrong scales; stepping back protects the other program too.
- **Alternatives**: Exclusive VXI-11 lock (rejected: not enforced by this scope); keep retrying
  with a warning (rejected by user: the other program may still receive wrong replies);
  auto-resume (rejected by user).
- **Limitation**: with `CHDR OFF` text replies cannot be validated (only binary ones); logged
  as a warning at connect.
- **Validated** *(measured, two real clients)*: with a second program polling `TDIV?`/`C1:VDIV?`,
  the app caught foreign replies (`'TDIV 50E-9 S'` for `C4:TRA?`, `b'C1:VDIV 1 V'` for
  `C3:WF? ALL`), never displayed them, and stopped after 6.4 s with the conflict message. The
  other symptom is **timeouts**: the other program reads first and takes our reply. So a
  connection lost after foreign replies (since the last clean cycle) also reports the conflict,
  and a connect timeout says "another program may be using the scope". Each device clear takes
  ~1 s on this scope. Alone, the app ran 109 clean cycles in 15 s (no false positives).
